"""内置接口文档（/wiki）：**只渲染 /openapi.json**，OpenAPI 范式，离线可用。

边界（刻意划清）：
- /wiki = 接口参考（端点 / 参数 / 请求示例 / 数据模型 / 错误码），内容 100% 来自 openapi.json，
  与实现同源、不可能漂移；
- 面向开发者的说明（语义、选型、运维、SDK 用法、快速开始）一律写在 README 与 docs/ 里，
  不在本页重复 —— 否则文档长成第二个 README，范式也就没了。
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

METHOD_ORDER = ("post", "get", "put", "delete", "patch")

TYPE_CN = {"object": "对象", "array": "数组", "string": "字符串", "integer": "整数",
           "number": "数值", "boolean": "布尔", "null": "空", "any": "任意"}


# ---------------------------------------------------------------- 小工具

def _schemas(doc: Dict[str, Any]) -> Dict[str, Any]:
    return ((doc.get("components") or {}).get("schemas") or {})


def _deref(node: Any, doc: Dict[str, Any], depth: int = 0) -> Any:
    if depth > 6 or not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[-1]
        target = _schemas(doc).get(name) or {}
        return {**target, "_ref_name": name}
    return node


def _type_label(prop: Dict[str, Any], doc: Dict[str, Any]) -> str:
    if "$ref" in prop:
        return _deref(prop, doc).get("_ref_name", "对象")
    if "anyOf" in prop:
        parts = []
        for sub in prop["anyOf"]:
            if isinstance(sub, dict) and sub.get("type") == "null":
                continue
            parts.append(_type_label(sub, doc))
        return " / ".join(p for p in parts if p) or "任意"
    t = prop.get("type")
    if isinstance(t, list):
        return " / ".join(TYPE_CN.get(x, x) for x in t)
    if t == "array":
        item = _type_label(prop.get("items") or {}, doc)
        return f"数组<{item}>"
    if t:
        return TYPE_CN.get(t, t)
    if prop.get("additionalProperties"):
        vt = _type_label(prop["additionalProperties"], doc) if isinstance(prop["additionalProperties"], dict) else "任意"
        return f"对象<{vt}>"
    return "任意"


def _example_of(prop: Dict[str, Any]) -> str:
    for key in ("examples", "example", "default"):
        if key in prop and prop[key] not in (None, [], {}):
            v = prop[key]
            if key == "examples" and isinstance(v, list):
                v = v[0]
            return json.dumps(v, ensure_ascii=False)[:120]
    return ""


def _schema_table(schema: Dict[str, Any], doc: Dict[str, Any]) -> str:
    schema = _deref(schema, doc)
    props = schema.get("properties") or {}
    if not props:
        return "<p class='hint'>（该模型无可展示字段）</p>"
    required = set(schema.get("required") or [])
    rows = []
    for name, raw in props.items():
        prop = _deref(raw, doc) if "$ref" not in raw else raw
        enum = raw.get("enum") or prop.get("enum")
        tlabel = _type_label(raw, doc) + (f"（{' / '.join(map(str, enum))}）" if enum else "")
        note = raw.get("description") or prop.get("description") or ""
        dflt = "" if raw.get("default") is None else json.dumps(raw["default"], ensure_ascii=False)
        ex = _example_of(raw)
        rows.append((name, tlabel, "是" if name in required else "否", dflt, note, ex))
    head = "<tr><th>字段</th><th>类型</th><th>必填</th><th>默认</th><th>说明</th><th>示例</th></tr>"
    body = "".join(
        f"<tr><td><code>{html.escape(n)}</code></td><td>{html.escape(t)}</td><td>{r}</td>"
        f"<td>{html.escape(d) if d else '—'}</td><td>{html.escape(s)}</td>"
        f"<td>{('<code>%s</code>' % html.escape(e)) if e else '—'}</td></tr>"
        for n, t, r, d, s, e in rows
    )
    return f"<table>{head}{body}</table>"


def _param_table(params: List[Dict[str, Any]]) -> str:
    if not params:
        return ""
    head = "<tr><th>参数</th><th>位置</th><th>类型</th><th>必填</th><th>说明</th></tr>"
    rows = "".join(
        f"<tr><td><code>{html.escape(p.get('name',''))}</code></td><td>{html.escape(p.get('in',''))}</td>"
        f"<td>{html.escape(((p.get('schema') or {}).get('type') or '—'))}</td>"
        f"<td>{'是' if p.get('required') else '否'}</td><td>{html.escape(p.get('description',''))}</td></tr>"
        for p in params
    )
    return f"<table>{head}{rows}</table>"


def _body_example(body: Dict[str, Any], doc: Dict[str, Any]) -> str:
    content = (body or {}).get("content") or {}
    for med, spec in content.items():
        schema = _deref(spec.get("schema") or {}, doc)
        for key in ("examples", "example"):
            v = schema.get(key)
            if v:
                if isinstance(v, dict) and key == "examples":
                    v = next(iter(v.values()), v)
                return f"<pre># {html.escape(med)}\n{html.escape(json.dumps(v, ensure_ascii=False, indent=2))}</pre>"
        props = schema.get("properties") or {}
        if props:
            placeholders = {"string": "<字符串>", "integer": 0, "number": 0, "boolean": False}

            def _placeholder(prop: Dict[str, Any]) -> Any:
                return placeholders.get(_deref(prop, doc).get("type"), "…")

            skeleton = {k: _placeholder(p) for k, p in props.items()}
            return f"<pre># {html.escape(med)}（结构骨架）\n{html.escape(json.dumps(skeleton, ensure_ascii=False, indent=2))}</pre>"
    return ""


def _response_rows(responses: Dict[str, Any], doc: Dict[str, Any]) -> str:
    head = "<tr><th>状态码</th><th>含义</th><th>返回模型</th></tr>"
    rows = []
    for code, spec in sorted(responses.items(), key=lambda kv: str(kv[0])):
        schema = ((spec.get("content") or {}).get("application/json") or {}).get("schema")
        ref = ""
        if isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"].rsplit("/", 1)[-1]
        elif isinstance(schema, dict):
            ref = _type_label(schema, doc)
        rows.append((str(code), spec.get("description", ""), ref))
    return "<table>" + head + "".join(
        f"<tr><td><code>{c}</code></td><td>{html.escape(d)}</td><td>{html.escape(r) if r else '—'}</td></tr>"
        for c, d, r in rows) + "</table>"


# ---------------------------------------------------------------- 页面

def build_page(doc: Optional[Dict[str, Any]] = None) -> str:
    doc = doc or {}
    paths = doc.get("paths") or {}
    schemas = _schemas(doc)
    info = doc.get("info") or {}

    endpoints = []
    for path, methods in sorted(paths.items()):
        for method in METHOD_ORDER:
            if method not in methods:
                continue
            op = methods[method]
            body = op.get("requestBody") or {}
            endpoints.append({
                "method": method.upper(), "path": path,
                "summary": op.get("summary", ""), "description": op.get("description", ""),
                "tags": op.get("tags") or ["default"],
                "params": op.get("parameters") or [],
                "body": body,
                "responses": op.get("responses") or {},
            })
    endpoints.sort(key=lambda e: (e["tags"][0], e["path"]))

    ep_html = []
    for e in endpoints:
        req_ref = ""
        schema = ((e["body"].get("content") or {}).get("application/json") or {}).get("schema") if e["body"] else None
        if isinstance(schema, dict) and "$ref" in schema:
            req_ref = schema["$ref"].rsplit("/", 1)[-1]
        badge = f'<span class="m {e["method"].lower()}">{e["method"]}</span>'
        ep_html.append(f"""
<section class="ep" id="ep-{e['method'].lower()}-{e['path'].strip('/').replace('/', '-') or 'root'}">
  <h3>{badge} <code>{html.escape(e['path'])}</code> <span class="hint">{html.escape(e['summary'])}</span></h3>
  {'<p>' + html.escape(e['description']).replace(chr(10), '<br/>') + '</p>' if e['description'] else ''}
  {_param_table(e['params'])}
  {('<p class="hint">请求体模型：<code>%s</code></p>' % html.escape(req_ref)) if req_ref else ''}
  {_body_example(e['body'], doc)}
  <p class="hint">响应：</p>
  {_response_rows(e['responses'], doc)}
</section>""")

    schema_html = []
    for name, raw in schemas.items():
        schema_html.append(f"<h3 id='schema-{html.escape(name)}'><code>{html.escape(name)}</code></h3>"
                           + (f"<p class='hint'>{html.escape(raw.get('description',''))}</p>" if raw.get("description") else "")
                           + _schema_table(raw, doc))

    title = info.get("title", "Laya 决策服务")
    version = info.get("version", "")
    desc = (info.get("description") or "").strip()

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)} {html.escape(version)} · 接口参考</title>
<style>
:root{{--bg:#0f1419;--panel:#171d24;--line:#263140;--fg:#e6edf3;--dim:#8b98a5;--acc:#4aa8ff;--code:#0d1117;--get:#3fb950;--post:#1f6feb}}
*{{box-sizing:border-box}}
body{{margin:0;font:14px/1.65 -apple-system,"PingFang SC",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}}
header{{padding:14px 22px;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:var(--bg);z-index:9}}
h1{{font-size:16px;margin:0}} a{{color:var(--acc);text-decoration:none}} a:hover{{text-decoration:underline}}
main{{max-width:1040px;margin:0 auto;padding:18px 22px 70px}}
nav.toc{{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 16px}}
nav.toc a{{border:1px solid var(--line);border-radius:999px;padding:3px 11px;font-size:12.5px;color:var(--fg)}}
h2{{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
h3{{font-size:14.5px;margin:18px 0 8px}}
section.ep{{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0;background:var(--panel)}}
.m{{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;border-radius:5px;padding:2px 7px;color:#fff;vertical-align:middle}}
.m.get{{background:var(--get)}} .m.post{{background:var(--post)}}
table{{width:100%;border-collapse:collapse;margin:8px 0 12px;font-size:13px}}
th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#131a22;color:var(--dim);font-weight:600;white-space:nowrap}}
code{{background:var(--code);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12.5px}}
pre{{background:var(--code);border:1px solid var(--line);border-radius:8px;padding:11px;overflow:auto;font-size:12.5px}}
.hint{{color:var(--dim);font-size:12.5px}}
</style></head>
<body>
<header>
  <h1>{html.escape(title)} <span class="hint">{html.escape(version)}</span></h1>
  <a href="/">测试台</a><a href="/openapi.json">openapi.json</a><a href="/docs">Swagger UI</a><a href="/redoc">ReDoc</a>
  <span class="hint" id="eng"></span>
</header>
<main>
<nav class="toc">
  <a href="#overview">概览</a><a href="#endpoints">接口</a><a href="#schemas">数据模型</a><a href="#errors">错误码</a><a href="#dev">开发者文档</a>
</nav>

<h2 id="overview">概览</h2>
<p>{html.escape(desc).replace(chr(10), '<br/>') if desc else ''}</p>
<p class="hint">answers 的键与请求 questions 一一对应；choice/score/noul 分别给 choice、score+legend、noul，均带 confidence（把握程度）。</p>

<h2 id="endpoints">接口</h2>
{''.join(ep_html)}

<h2 id="schemas">数据模型（由 pydantic 模型自动生成）</h2>
{''.join(schema_html)}

<h2 id="errors">错误码</h2>
<table><tr><th>错误码</th><th>HTTP</th><th>何时出现</th></tr>
<tr><td><code>SCHEMA_INVALID</code></td><td>400</td><td>字段类型/选项不合法（choice 标签重复、state_format 与 state 不匹配等）</td></tr>
<tr><td><code>UNAUTHORIZED</code></td><td>401</td><td>未带或错误的密钥（服务端开启 <code>LAYA_AUTH_MODE=api_key</code> 时）</td></tr>
<tr><td><code>OVER_BUDGET</code></td><td>413</td><td>情境或选项超 token 预算（truncate_state=false 时）</td></tr>
<tr><td><code>RATE_LIMITED</code></td><td>429</td><td>超出该密钥的速率上限；响应带 <code>Retry-After</code></td></tr>
<tr><td><code>BUSY</code></td><td>503</td><td>排队已满（并发过高）</td></tr>
<tr><td><code>MODEL_UNAVAILABLE</code></td><td>503</td><td>后端/权重不可用</td></tr>
<tr><td><code>TIMEOUT</code></td><td>504</td><td>超过 timeout_ms；底层推理跑完才释放 worker</td></tr>
<tr><td><code>INTERNAL</code></td><td>500</td><td>其它未预期错误</td></tr></table>

<h2 id="dev">开发者文档（不在本页展开）</h2>
<table><tr><th>想看什么</th><th>去哪</th></tr>
<tr><td>快速开始、部署、运维与安全（鉴权/限流/性能开关）</td><td><code>README.md</code></td></tr>
<tr><td>三种问法怎么选、返回怎么读、误用与选型</td><td><code>docs/api-semantics.md</code></td></tr>
<tr><td>Java / TypeScript / Python 客户端用法</td><td><code>docs/sdk.md</code></td></tr>
<tr><td>全部环境变量清单</td><td><code>.env.example</code></td></tr>
<tr><td>版本化契约（JSON Schema）</td><td><code>contract/decision.v1.schema.json</code></td></tr></table>
</main>
<script>
fetch('/v1/status').then(r=>r.json()).then(s=>{{
  document.getElementById('eng').textContent = (s.engine?.engine_mode||'-') + ' / ' + (s.engine?.model||'-') + ' / ' + (s.engine?.backend||'-');
}}).catch(()=>{{}});
</script>
</body></html>
"""
