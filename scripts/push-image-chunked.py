#!/usr/bin/env python3
"""把 `docker save` 产物分块推送到 registry（应对"单个大请求被中间设备掐断"的网络）。

为什么需要它
------------
标准推送（docker push / crane push）把**整个层**放在一个 HTTP 请求里。层大、上行慢时，
这个请求可能跑几十分钟，中间任何一跳超时/重置（实测：代理返回 502 Bad Gateway）就会前功尽弃，
且 registry 侧该次上传会话作废。本脚本改为：

  · 每层用 32MiB 分块 PATCH 上传，失败只重传该块；
  · 失败后向 registry 查询已提交偏移（Range/Docker-Upload-Offset），从该偏移续传，不重头来；
  · 已存在的 blob 先 HEAD，跳过（不重复传）；
  · 顺手把层重新 gzip（docker save 在 containerd/OCI 模式下层是**未压缩**的 tar，
    gzip 后上行与用户 pull 的体积都能省 40% 左右）。

用法
----
    HTTPS_PROXY=http://127.0.0.1:7890 python3 scripts/push-image-chunked.py \
        --tar /root/push/laya-decision-api-1.0.1-amd64.tar \
        --repo bmw8080/laya-decision-api \
        --tag 1.0.1 --tag latest

凭据从 `~/.docker/config.json` 读（docker login / crane auth login 写的那份）。
断点续传：临时 gz 文件与每层状态记在 --workdir（默认与 tar 同目录的 .pushwork/），重跑即续。
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 8 * 1024 * 1024           # 每块 8MiB（块别太大：链路偶发 TLS 重置，小块失败重传代价低）
AUTH_HOST = "https://auth.docker.io/token"
REGISTRY = "https://index.docker.io"
SERVICE = "registry.docker.io"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def opener():
    handlers = []
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
        log(f"走代理：{proxy}")
    else:
        log("未设置 HTTPS_PROXY（直连）")
    return urllib.request.build_opener(*handlers)


def with_retry(fn, what: str, tries: int = 6, base: float = 4.0):
    """链路偶发 TLS 重置（UNEXPECTED_EOF / 502），关键请求统一包一层重试。"""
    last = None
    for i in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"    {what} 第 {i}/{tries} 次失败：{type(e).__name__}: {str(e)[:90]}")
            time.sleep(min(60, base * i))
    raise RuntimeError(f"{what} 连续 {tries} 次失败：{last}")


class Reg:
    def __init__(self, repo: str):
        self.repo = repo
        self.op = opener()
        cfg = json.load(open(os.path.expanduser("~/.docker/config.json"), encoding="utf-8"))
        auths = cfg.get("auths") or {}
        entry = None
        for k in ("https://index.docker.io/v1/", "docker.io", "index.docker.io", REGISTRY + "/v1/"):
            if k in auths:
                entry = auths[k]
                break
        if not entry:
            raise SystemExit("~/.docker/config.json 里没有 docker.io 凭据，先 crane auth login / docker login")
        user, pw = base64.b64decode(entry["auth"]).decode().split(":", 1)
        self.basic = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
        self.tok = ""
        self.tok_at = 0.0

    def _token(self) -> str:
        if self.tok and time.time() - self.tok_at < 240:
            return self.tok
        scope = f"repository:{self.repo}:push,pull"
        url = AUTH_HOST + "?" + urllib.parse.urlencode({"service": SERVICE, "scope": scope})

        def _fetch():
            req = urllib.request.Request(url, headers={"Authorization": self.basic})
            with self.op.open(req, timeout=60) as r:
                return json.load(r)["token"]

        self.tok = with_retry(_fetch, "取 Docker Hub 令牌")
        self.tok_at = time.time()
        return self.tok

    def req(self, method: str, url: str, data=None, headers=None, ok=(200, 201, 202, 204), timeout=300, retries=4):
        """带鉴权与重试的请求；url 可以是 /v2/... 相对路径或绝对地址。"""
        h = dict(headers or {})
        if url.startswith("/"):
            url = REGISTRY + url
        last = None
        for attempt in range(1, retries + 1):
            h["Authorization"] = "Bearer " + self._token()
            h.setdefault("User-Agent", "push-image-chunked/1.0")
            req = urllib.request.Request(url, data=data, method=method, headers=h)
            try:
                with self.op.open(req, timeout=timeout) as r:
                    if r.status not in ok:
                        raise RuntimeError(f"HTTP {r.status}")
                    return r
            except urllib.error.HTTPError as e:
                body = e.read()[:200]
                if e.code == 401 and attempt < retries:
                    self.tok = ""
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    last = f"HTTP {e.code}"
                    time.sleep(min(60, 5 * attempt))
                    continue
                raise RuntimeError(f"HTTP {e.code} {body!r}") from None
            except Exception as e:  # 网络层异常（超时、连接重置）
                last = f"{type(e).__name__}: {e}"
                if attempt < retries:
                    time.sleep(min(60, 5 * attempt))
                    continue
                raise RuntimeError(last) from None
        raise RuntimeError(last or "unknown")

    def blob_exists(self, digest: str) -> bool:
        try:
            self.req("HEAD", f"/v2/{self.repo}/blobs/{digest}", ok=(200,))
            return True
        except Exception:
            return False

    def upload_offset(self, session_url: str) -> int:
        r = self.req("GET", session_url, ok=(204, 200))
        rng = r.headers.get("Range") or r.headers.get("Docker-Upload-Offset") or ""
        if not rng:
            return 0
        tail = rng.split("-")[-1].strip()
        try:
            return int(tail) + 1 if "-" in rng else int(tail)
        except ValueError:
            return 0

    def push_blob(self, path: str, digest: str, size: int) -> None:
        r = self.req("POST", f"/v2/{self.repo}/blobs/uploads/", data=b"", headers={"Content-Length": "0"})
        loc = r.headers.get("Location")
        if not loc:
            raise RuntimeError("上传会话没有返回 Location")
        session = loc if loc.startswith("http") else REGISTRY + loc
        off = 0
        with open(path, "rb") as f:
            while off < size:
                f.seek(off)
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                for attempt in range(1, 9):
                    try:
                        # 三条实测得来的硬要求（踩了很久）：
                        #  1) 不要带 Content-Range —— Docker Hub 会回 416 RANGE_INVALID，用纯追加；
                        #  2) **必须用每次响应返回的新 Location 继续传**：里面带更新后的状态令牌，
                        #     沿用最初那个 URL，第二块起必然 416；
                        #  3) PATCH 不做内部重试（万一服务端其实已提交，重发会重复追加），失败交给外层查 offset 续传。
                        r = self.req("PATCH", session, data=chunk, ok=(202,), retries=1,
                                     headers={"Content-Type": "application/octet-stream"})
                        nxt = r.headers.get("Location")
                        if nxt:
                            session = nxt if nxt.startswith("http") else REGISTRY + nxt
                        rng = r.headers.get("Range") or ""
                        off = (int(rng.split("-")[-1]) + 1) if rng else off + len(chunk)
                        log(f"    {os.path.basename(path)}: {off / 1048576:.0f}/{size / 1048576:.0f} MB"
                            f" ({100.0 * off / size:.0f}%)")
                        break
                    except Exception as e:  # noqa: BLE001
                        log(f"    分块失败（第 {attempt} 次，已传 {off / 1048576:.0f} MB）：{e}")
                        time.sleep(min(60, 4 * attempt))
                        try:
                            off = self.upload_offset(session)   # 向 registry 问实际已提交偏移，从那里续
                        except Exception as e2:  # noqa: BLE001
                            log(f"    查询偏移失败（{e2}）——保守从头续")
                            off = 0
                else:
                    raise RuntimeError("分块重试次数用尽")
        sep = "&" if "?" in session else "?"
        self.req("PUT", f"{session}{sep}digest={urllib.parse.quote(digest)}",
                 data=b"", headers={"Content-Length": "0"}, ok=(201, 204))
        log(f"    ✔ 已提交 {digest[:19]}… ({size / 1048576:.0f} MB)")

    def put_manifest(self, tag: str, manifest: dict) -> None:
        body = json.dumps(manifest).encode()
        ct = manifest["mediaType"]
        self.req("PUT", f"/v2/{self.repo}/manifests/{tag}", data=body,
                 headers={"Content-Type": ct, "Content-Length": str(len(body))}, ok=(201, 201, 200))


def gzip_layer(src_tar: str, member: str, out_path: str, expect_diffid: str | None = None) -> tuple[str, int, str]:
    """把 tar 里的某一层压成 gzip 写到 out_path。

    返回 (blob_digest, 压缩后大小, diffID)：
      · blob_digest = **压缩后**内容的 sha256 —— 这是 registry 里 blob 的名字，manifest 必须引用它
      · diffID      = **未压缩**内容的 sha256 —— 必须与 config.rootfs.diff_ids 一致（校验用）
    已压过则直接复用（断点续传）。
    """
    state = out_path + ".json"
    if os.path.exists(out_path) and os.path.exists(state):
        st = json.load(open(state))
        if not expect_diffid or st.get("diffid") == expect_diffid:
            return st["digest"], st["size"], st.get("diffid", "")
    h_raw = hashlib.sha256()
    n = 0
    t0 = time.time()
    with tarfile.open(src_tar, "r") as t, open(out_path, "wb") as fo:
        gz = gzip.GzipFile(fileobj=fo, mode="wb", compresslevel=1, mtime=0)
        f = t.extractfile(member)
        while True:
            buf = f.read(8 * 1024 * 1024)
            if not buf:
                break
            h_raw.update(buf)
            gz.write(buf)
            n += len(buf)
        gz.close()
        size = fo.tell()
    diffid = "sha256:" + h_raw.hexdigest()
    h_gz = hashlib.sha256()
    with open(out_path, "rb") as fr:
        while True:
            b = fr.read(8 * 1024 * 1024)
            if not b:
                break
            h_gz.update(b)
    digest = "sha256:" + h_gz.hexdigest()
    json.dump({"digest": digest, "size": size, "raw": n, "diffid": diffid}, open(state, "w"))
    flag = "" if (expect_diffid and diffid == expect_diffid) else ("  ← diffID 与 config 不一致，检查取层顺序" if expect_diffid else "")
    log(f"    压缩 {member[-12:]}：{n / 1048576:.0f}MB → {size / 1048576:.0f}MB（{time.time() - t0:.0f}s）{flag}")
    return digest, size, diffid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tar", required=True)
    ap.add_argument("--repo", required=True, help="例：bmw8080/laya-decision-api")
    ap.add_argument("--tag", action="append", required=True)
    ap.add_argument("--workdir", default=None)
    a = ap.parse_args()

    work = a.workdir or os.path.join(os.path.dirname(os.path.abspath(a.tar)), ".pushwork")
    os.makedirs(work, exist_ok=True)
    reg = Reg(a.repo)

    with tarfile.open(a.tar, "r") as t:
        man = json.loads(t.extractfile("manifest.json").read())[0]
        cfg_member = man["Config"]
        cfg = json.loads(t.extractfile(cfg_member).read())
        layers = man["Layers"]
        sources = man.get("LayerSources") or {}

    # 1) config blob（很小，存在就跳过）
    cfg_digest = "sha256:" + cfg_member.split("/")[-1]
    with tarfile.open(a.tar, "r") as t:
        cfg_bytes = t.extractfile(cfg_member).read()
    cfg_size = len(cfg_bytes)
    if reg.blob_exists(cfg_digest):
        log(f"config blob 已存在，跳过（{cfg_digest[:19]}…, {cfg_size} B）")
    else:
        p = os.path.join(work, "config.json")
        open(p, "wb").write(cfg_bytes)
        log("上传 config blob")
        reg.push_blob(p, cfg_digest, cfg_size)

    # 2) 逐层：gzip → 分块上传（已存在的 blob 跳过）
    layer_entries = []
    total_up = 0
    for i, member in enumerate(layers, 1):
        src = sources.get("sha256:" + member.split("/")[-1])
        raw_size = src["size"] if src else None
        log(f"层 {i}/{len(layers)}：{member[-12:]}（原始 {(raw_size or 0) / 1048576:.0f} MB）")
        gz_path = os.path.join(work, f"L{i:02d}.tar.gz")
        digest, size, _ = gzip_layer(a.tar, member, gz_path,
                                     expect_diffid=cfg["rootfs"]["diff_ids"][i - 1])
        layer_entries.append({"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                              "size": size, "digest": digest})
        if reg.blob_exists(digest):
            log("    该层已在 registry，跳过上传")
            continue
        total_up += size
        log(f"    上传（{size / 1048576:.0f} MB，分块 {CHUNK // 1048576}MiB）")
        reg.push_blob(gz_path, digest, size)

    # 3) 写 manifest（docker schema2：层 gzip，diffID 与 config 一致）
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"mediaType": "application/vnd.docker.container.image.v1+json",
                   "size": cfg_size, "digest": cfg_digest},
        "layers": layer_entries,
    }
    for tag in a.tag:
        reg.put_manifest(tag, manifest)
        log(f"✔ 已发布 {a.repo}:{tag}")

    log(f"完成。本次新上传约 {total_up / 1048576:.0f} MB；临时文件在 {work}（可删）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
