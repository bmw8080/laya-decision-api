#!/bin/bash
# 打成一个可以拷到别的机器（含 x86_64 服务器）的离线交付包。
#
# 干什么：环境自检 → 构建镜像 → 镜像内自检 → docker save 压缩 + 校验和
#         （可选 WITH_WEIGHTS=1 时把 644MB 权重也一起打包）→ 打印服务器侧命令
#
# 用法：
#   bash scripts/docker-ship.sh [TAG] [输出目录]
#   PLATFORM=linux/amd64 bash scripts/docker-ship.sh laya-decision-api:1.0.1 ./dist
#   WITH_WEIGHTS=1 bash scripts/docker-ship.sh                      # 连权重一起打包（离线服务器用）
#
# 关键前提：**镜像架构 = 构建机架构**。在 x86_64 的 Ubuntu VM 上构建 → 产物就是 linux/amd64，
# 直接拷到 x86_64 服务器 `docker load` 即可跑；在 Apple Silicon 上构建则是 arm64，不能拷给 x86。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 默认 TAG 的版本号取自 pyproject.toml（唯一来源），避免镜像标签与工程版本脱节
VER_DEFAULT="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "${ROOT}/pyproject.toml" | head -1)"
TAG="${1:-laya-decision-api:${VER_DEFAULT:-latest}}"
OUT="${2:-${ROOT}/dist}"
PLATFORM="${PLATFORM:-}"
WITH_WEIGHTS="${WITH_WEIGHTS:-0}"
MODELS_HOST="${LAYA_MODELS_HOST:-/opt/laya-models}"
MODEL="${LAYA_MODEL:-multilingual}"
mkdir -p "$OUT"

hr() { printf '─%.0s' {1..66}; echo; }

hr; echo "0) 环境自检"; hr
HOST_ARCH="$(uname -m)"
echo "  构建机架构 ：${HOST_ARCH}"
if ! command -v docker >/dev/null 2>&1; then
  echo "  ✗ 没有 docker：本机无法构建。请在装有 Docker 的机器（如 Ubuntu VM）上跑本脚本。" >&2
  exit 1
fi
echo "  docker     ：$(docker version --format '{{.Server.Version}}' 2>/dev/null || docker --version)"
if docker buildx version >/dev/null 2>&1; then echo "  buildx     ：可用（可跨架构构建）"; else echo "  buildx     ：无（只能构建构建机架构）"; fi
case "${HOST_ARCH}" in
  x86_64|amd64) echo "  结论     ：将产出 linux/amd64 镜像 —— 可直接拷到 x86_64 服务器运行 ✔";;
  arm64|aarch64)
    if [ "${PLATFORM}" = "linux/amd64" ]; then
      echo "  结论     ：构建机是 arm64，但指定了 --platform linux/amd64（QEMU 模拟，会慢）→ 产物仍是 x86 可跑 ✔"
    else
      echo "  警告     ：构建机是 arm64 且未指定 PLATFORM → 产物是 linux/arm64，拷到 x86_64 服务器会 exec format error" >&2
      echo "             要 x86 产物请用：PLATFORM=linux/amd64 bash scripts/docker-ship.sh ${TAG} ${OUT}" >&2
    fi;;
esac
df -h "$OUT" | tail -1 | awk '{print "  磁盘可用   ：" $4 " （" $9 "）"}'

hr; echo "1) 构建镜像 ${TAG}"; hr
if [ -n "${PLATFORM}" ]; then PLATFORM="${PLATFORM}" bash "${ROOT}/scripts/docker-build.sh" "${TAG}"
else bash "${ROOT}/scripts/docker-build.sh" "${TAG}"; fi

IMG_OSARCH="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${TAG}")"
IMG_ARCH="${IMG_OSARCH##*/}"

hr; echo "2) 镜像内自检（真实导入依赖，不挂权重）"; hr
docker run --rm --entrypoint python "${TAG}" -c \
  "import platform, torch, fastapi, uvicorn, laya; \
print('  容器内架构 :', platform.machine()); \
print('  torch      :', torch.__version__); \
print('  laya       :', getattr(laya, '__version__', '仓库版')); \
print('  依赖自检   : ok')"

hr; echo "3) 导出离线包"; hr
VER_PART="${TAG##*:}"
case "${VER_PART}" in
  *"${IMG_ARCH}") BASE_NAME="laya-decision-api-${VER_PART}" ;;              # 标签里已带架构，不重复拼
  *)               BASE_NAME="laya-decision-api-${VER_PART}-${IMG_ARCH}" ;; # 名-版本-架构，与 /opt 交付件命名一致
esac
TARBALL="${OUT}/${BASE_NAME}.tar.gz"
echo "  docker save → ${TARBALL}（约 1–2GB，视基础镜像而定）"
docker save "${TAG}" | gzip -1 > "${TARBALL}"
( cd "${OUT}" && shasum -a 256 "${BASE_NAME}.tar.gz" > "${BASE_NAME}.tar.gz.sha256" 2>/dev/null \
  || sha256sum "${BASE_NAME}.tar.gz" > "${BASE_NAME}.tar.gz.sha256" )
echo "  大小       ：$(du -h "${TARBALL}" | cut -f1)"
echo "  校验和     ：$(cat "${OUT}/${BASE_NAME}.tar.gz.sha256")"

WEIGHTS_TGZ=""
hr; echo "4) 权重"; hr
if [ "${WITH_WEIGHTS}" != "1" ]; then
  echo "  跳过（服务器能上 ModelScope 就直接在服务器上跑 scripts/fetch-weights.sh；"
  echo "        完全离线就重跑本脚本并加 WITH_WEIGHTS=1，把权重一起打出来）"
fi
if [ "${WITH_WEIGHTS}" = "1" ]; then
  if [ ! -e "${MODELS_HOST}/${MODEL}/model.safetensors" ]; then
    echo "  拉取权重到 ${MODELS_HOST} ..."
    bash "${ROOT}/scripts/fetch-weights.sh" "${MODELS_HOST}"
  fi
  WEIGHTS_TGZ="${OUT}/laya-models-${MODEL}.tar.gz"
  tar czf "${WEIGHTS_TGZ}" -C "${MODELS_HOST}" "${MODEL}"
  ( cd "${OUT}" && shasum -a 256 "$(basename "${WEIGHTS_TGZ}")" > "$(basename "${WEIGHTS_TGZ}").sha256" 2>/dev/null \
    || sha256sum "$(basename "${WEIGHTS_TGZ}")" > "$(basename "${WEIGHTS_TGZ}").sha256" )
  echo "  权重包     ：${WEIGHTS_TGZ} （$(du -h "${WEIGHTS_TGZ}" | cut -f1)）"
else
  echo "  （跳过权重：需要一起打包就加 WITH_WEIGHTS=1）"
fi

hr; echo "5) 拷到 x86_64 服务器后执行"; hr
cat <<EOF
  # 传输（示例）
  scp ${TARBALL} user@server:/tmp/${BASE_NAME}.tar.gz
$([ -n "${WEIGHTS_TGZ}" ] && echo "  scp ${WEIGHTS_TGZ} user@server:/tmp/")
$(cd "${OUT}" && echo "  scp ${BASE_NAME}.tar.gz.sha256 user@server:/tmp/")

  # 服务器上：校验 → 载入 → 准备权重 → 起服务
  cd /tmp && sha256sum -c ${BASE_NAME}.tar.gz.sha256
  docker load < ${BASE_NAME}.tar.gz
  docker image inspect ${TAG} --format '镜像架构：{{.Os}}/{{.Architecture}}'
$([ -n "${WEIGHTS_TGZ}" ] && cat <<EOF2
  mkdir -p ${MODELS_HOST} && tar xzf $(basename "${WEIGHTS_TGZ}") -C ${MODELS_HOST}
EOF2
)  # 若服务器不能上 ModelScope 就用上面的权重包；能上就直接 bash scripts/fetch-weights.sh ${MODELS_HOST}
  cp .env.docker.example .env.docker      # 按需改 LAYA_API_KEYS / 端口
  bash scripts/docker-run.sh ${TAG}
  curl -s 'http://127.0.0.1:8765/readyz?warm=1'    # 期望 loaded:["torch/multilingual"]

  # x86_64 服务器 CPU 需支持 AVX2（torch 官方 wheel 编译依赖）；先确认：
  lscpu | grep -o avx2 || echo "该 CPU 无 AVX2：torch 可能 illegal instruction，需换源码编译版 torch"
EOF
hr; echo "完成：${OUT}"; ls -lh "${OUT}"
