"""OpenAPI 3.1 → 3.0.3 降级转换（给只认 3.0.x 的平台导入用）。

为什么需要：FastAPI 生成的是 **OpenAPI 3.1.0**，而不少企业级 API 平台（API 网关、API 管理、
Apifox/YApi 之类）只认 **3.0.x**，导入时会报「无法读取 openapi 信息 / 版本不是 3.0.x」。

3.1 与 3.0 在文档层面的差异（本模块处理的就是这些）：
  1. `type: "null"`（以及 `type: ["string","null"]` 数组型 type）—— 3.0 没有 null 类型，要用 `nullable: true`
  2. schema 级 `examples: [...]`（3.1 写法）—— 3.0 是单数 `example:`
  3. `const: v` —— 3.0 用 `enum: [v]`
  4. `exclusiveMinimum/Maximum` 为数值（3.1）—— 3.0 是布尔开关 + `minimum/maximum`
  5. `$ref` 带兄弟键 —— 3.0 里会被忽略，改成 `allOf: [{$ref}] + 兄弟键`
  6. 3.0 不认识的 JSON Schema 关键字（`prefixItems` / `patternProperties` / `contentMediaType` …）—— 移除
  7. 顶层 `jsonSchemaDialect` / `webhooks`（3.1 专有）—— 移除

用法：
    from laya_api.openapi30 import to_openapi_30
    doc30 = to_openapi_30(app.openapi())

命令行（导出成文件给平台上传）：
    python -m laya_api.openapi30 > openapi-3.0.json
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

TARGET_VERSION = "3.0.3"

# 3.0 规范里不存在的 JSON Schema 关键字：直接删掉，避免校验器/导入器报未知字段
_DROP_KEYS = {
    "$schema", "jsonSchemaDialect", "contentMediaType", "contentEncoding", "prefixItems",
    "unevaluatedProperties", "unevaluatedItems", "patternProperties", "propertyNames",
    "dependentSchemas", "dependentRequired", "if", "then", "else", "const",
}


def _is_null_schema(node: Any) -> bool:
    return isinstance(node, dict) and (node.get("type") == "null" or (isinstance(node.get("type"), list) and node["type"] == ["null"]))


def _fix_schema(node: Any) -> Any:
    """递归把 3.1 写法改写成 3.0 写法。"""
    if isinstance(node, list):
        return [_fix_schema(x) for x in node]
    if not isinstance(node, dict):
        return node

    out: Dict[str, Any] = {}

    for key, val in node.items():
        if key in _DROP_KEYS:
            continue
        out[key] = _fix_schema(val)

    # 1) type 数组 / type: null → nullable
    t = out.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        if len(non_null) != len(t):
            out["nullable"] = True
        if len(non_null) == 1:
            out["type"] = non_null[0]
        elif non_null:
            out["type"] = non_null
            out.pop("nullable", None)  # 多类型 3.0 也不支持，只能保留信息，交给 anyOf 分支处理
        else:
            out.pop("type", None)
    elif t == "null":
        out.pop("type", None)
        out["nullable"] = True

    # 2) anyOf / oneOf 里的 null 分支 → nullable；单分支直接内联
    for combiner in ("anyOf", "oneOf"):
        branches = out.get(combiner)
        if not isinstance(branches, list):
            continue
        non_null_branches = [b for b in branches if not _is_null_schema(b)]
        if len(non_null_branches) != len(branches):
            out["nullable"] = True
        if not non_null_branches:
            out.pop(combiner, None)
        elif len(non_null_branches) == 1:
            single = non_null_branches[0]
            out.pop(combiner, None)
            if isinstance(single, dict):
                merged = dict(single)
                for k, v in out.items():          # 保留 description/title/example 等兄弟键
                    merged.setdefault(k, v)
                out = merged
            else:
                out = {"type": str(single)}
        else:
            out[combiner] = non_null_branches

    # 3) schema 级 examples: [...] → example
    if "examples" in out and isinstance(out["examples"], list) and out["examples"]:
        out.setdefault("example", out["examples"][0])
        out.pop("examples", None)

    # 4) const → enum（上面已 drop，这里兜一遍以防嵌套情况）
    if "const" in out:
        out["enum"] = [out.pop("const")]

    # 5) 数值型 exclusiveMinimum/Maximum → 布尔开关
    for excl, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        v = out.get(excl)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[bound] = v
            out[excl] = True

    # 6) $ref 带兄弟键 → allOf 包装（3.0 里 $ref 的兄弟键会被忽略）
    if "$ref" in out and len(out) > 1:
        ref = out.pop("$ref")
        wrapped: Dict[str, Any] = {"allOf": [{"$ref": ref}]}
        wrapped.update(out)          # 兄弟键（description/title/example 等）放到 allOf 同级
        out = wrapped

    return out


def _walk_paths(paths: Dict[str, Any]) -> Dict[str, Any]:
    methods = ("get", "post", "put", "patch", "delete", "head", "options")
    out: Dict[str, Any] = {}
    for path, item in (paths or {}).items():
        fixed_item: Dict[str, Any] = {}
        for key, val in (item or {}).items():
            if key in methods and isinstance(val, dict):
                op = _fix_schema(val)
                # 保证 operationId 存在（部分平台导入时依赖它做唯一标识）
                op.setdefault("operationId", f"{key}_{path.strip('/').replace('/', '_').replace('{','').replace('}','') or 'root'}")
                # 保证有 responses（导入器普遍要求）
                op.setdefault("responses", {"200": {"description": "OK"}})
                fixed_item[key] = op
            else:
                fixed_item[key] = _fix_schema(val)
        out[path] = fixed_item
    return out


def to_openapi_30(doc: Dict[str, Any], server_url: Optional[str] = None) -> Dict[str, Any]:
    """把 FastAPI 产出的 OpenAPI 3.1 文档降级为 3.0.3。"""
    src = copy.deepcopy(doc)
    out: Dict[str, Any] = {
        "openapi": TARGET_VERSION,
        "info": src.get("info", {}),
        "paths": _walk_paths(src.get("paths", {})),
    }
    if src.get("tags"):
        out["tags"] = _fix_schema(src["tags"])
    comps = src.get("components") or {}
    new_comps: Dict[str, Any] = {}
    if comps.get("schemas"):
        new_comps["schemas"] = {k: _fix_schema(v) for k, v in comps["schemas"].items()}
    for extra in ("securitySchemes", "parameters", "responses", "requestBodies", "headers"):
        if comps.get(extra):
            new_comps[extra] = _fix_schema(comps[extra])
    if new_comps:
        out["components"] = new_comps
    # 3.0 里 servers 常用：缺省给一个相对根路径，平台可按需要覆盖
    servers = src.get("servers")
    if not servers:
        if server_url:
            servers = [{"url": server_url, "description": "服务地址"}]
        else:
            servers = [{"url": "/", "description": "相对路径；按部署地址补全 host，或用 LAYA_OPENAPI_SERVER_URL 写死"}]
    out["servers"] = servers
    return out


# ============================================================
# 「平台友好」扁平化档（给金蝶苍穹等自研转换器用）
# ============================================================
# 背景：苍穹的 JsonSchemaToParamDefinitionConverter.convertSchema 在遇到它不认识的
# schema 形状时会 NPE（实测报错：convertSchema:150）。已知它处理不了/容易出问题的写法：
#   $ref（不解析/解析后为 null）、allOf/anyOf/oneOf、additionalProperties 无类型、无 type 的 schema。
# 所以这一档把文档彻底摊平：**内联所有 $ref、消掉 anyOf/oneOf/allOf、每个 schema 节点都带 type**。
# 语义等价性：对象照旧；联合类型取"信息最全的那一支"并在 description 里说明；递归引用用占位对象表示。

_KEEP = {"type", "title", "description", "properties", "required", "items", "enum", "default",
         "example", "additionalProperties", "format", "minimum", "maximum", "nullable", "pattern"}

_CYCLE_PLACEHOLDER = {"type": "object", "description": "（递归引用：按对象/字典处理）"}


def _infer_type(node: Dict[str, Any]) -> str:
    """没有 type 时按结构/示例推断一个具体类型（苍穹侧缺 type 就会炸）。"""
    if "properties" in node or "additionalProperties" in node:
        return "object"
    if "items" in node:
        return "array"
    ex = node.get("example", node.get("examples"))
    if isinstance(ex, dict):
        return "object"
    if isinstance(ex, list):
        return "array"
    if isinstance(ex, bool):
        return "boolean"
    if isinstance(ex, (int, float)):
        return "number"
    if node.get("enum"):
        vals = node["enum"]
        if all(isinstance(v, str) for v in vals):
            return "string"
        if all(isinstance(v, bool) for v in vals):
            return "boolean"
        if all(isinstance(v, int) for v in vals):
            return "integer"
    return "object"


def _flatten(node: Any, schemas: Dict[str, Any], seen: frozenset) -> Any:
    if isinstance(node, list):
        return [_flatten(x, schemas, seen) for x in node]
    if not isinstance(node, dict):
        return node

    # 1) $ref → 内联（带环保护）
    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name in seen or name not in schemas:
            out = dict(_CYCLE_PLACEHOLDER)
        else:
            out = _flatten(schemas[name], schemas, seen | {name})
        for k, v in node.items():           # $ref 的兄弟键（description 等）覆盖上去
            if k != "$ref":
                out.setdefault(k, _flatten(v, schemas, seen))
        node = out

    # 2) allOf → 合并分支
    if isinstance(node.get("allOf"), list):
        merged: Dict[str, Any] = {}
        for br in node["allOf"]:
            f = _flatten(br, schemas, seen)
            if isinstance(f, dict):
                props = dict(merged.get("properties") or {})
                props.update(f.get("properties") or {})
                req = list(dict.fromkeys((merged.get("required") or []) + (f.get("required") or [])))
                merged.update({k: v for k, v in f.items() if k != "properties"})
                if props:
                    merged["properties"] = props
                if req:
                    merged["required"] = req
        for k, v in node.items():
            if k != "allOf":
                merged.setdefault(k, _flatten(v, schemas, seen))
        node = merged

    # 3) anyOf / oneOf → 取"信息最全"的一支
    for combiner in ("anyOf", "oneOf"):
        if isinstance(node.get(combiner), list) and node[combiner]:
            branches = [b for b in node[combiner] if not _is_null_schema(b)]
            if not branches:
                branches = node[combiner]
            best = max(branches, key=lambda b: len(json.dumps(b, ensure_ascii=False)))
            flat = _flatten(best, schemas, seen)
            if isinstance(flat, dict):
                extra: Dict[str, Any] = {}
                for k, v in node.items():
                    if k == combiner:
                        continue
                    # 同 step 4：只有承载 schema 的键才递归，example/enum 是数据
                    extra[k] = _flatten(v, schemas, seen) if k in ("items", "additionalProperties", "not") else v
                flat.update({k: v for k, v in extra.items() if k not in flat or k == "description"})
            node = flat

    # 4) 逐键处理：只有「承载 schema 的键」才继续递归；example/default/enum 是**数据**，原样保留
    out2: Dict[str, Any] = {}
    for k, v in node.items():
        if k not in _KEEP or k == "properties":
            continue
        if k in ("items", "additionalProperties", "not"):
            out2[k] = _flatten(v, schemas, seen)
        else:
            out2[k] = v

    # additionalProperties 是布尔值时归一化（部分自研转换器看到 true/false 会挂）
    ap = out2.get("additionalProperties")
    if ap is True:
        out2["additionalProperties"] = {"type": "string", "description": "任意值（平台侧按字符串处理）"}
    elif ap is False:
        out2.pop("additionalProperties", None)

    props = node.get("properties")
    if isinstance(props, dict):
        out2["properties"] = {pk: _flatten(pv, schemas, seen) for pk, pv in props.items()}

    items = out2.get("items")
    if isinstance(items, list):
        out2["items"] = _flatten(items[0], schemas, seen) if items else {}

    # 5) 保证有 type（苍穹侧缺 type 会 NPE）
    if "type" not in out2:
        out2["type"] = _infer_type(out2)
    # 对象必须带 properties 或 additionalProperties，避免下游拿到空对象
    if out2.get("type") == "object" and "properties" not in out2 and "additionalProperties" not in out2:
        out2.setdefault("additionalProperties", {"type": "string"})
    return out2


def _flatten_operation(op: Dict[str, Any], schemas: Dict[str, Any]) -> Dict[str, Any]:
    """operation 本身不是 schema：保留 summary/operationId/responses 等结构，只摊平其中的 schema。"""
    out = copy.deepcopy(op)
    for p in out.get("parameters") or []:
        if isinstance(p, dict) and isinstance(p.get("schema"), dict):
            p["schema"] = _flatten(p["schema"], schemas, frozenset())
    rb = out.get("requestBody") or {}
    for spec in (rb.get("content") or {}).values():
        if isinstance(spec, dict) and isinstance(spec.get("schema"), dict):
            spec["schema"] = _flatten(spec["schema"], schemas, frozenset())
    for spec in (out.get("responses") or {}).values():
        if not isinstance(spec, dict):
            continue
        for mspec in (spec.get("content") or {}).values():
            if isinstance(mspec, dict) and isinstance(mspec.get("schema"), dict):
                mspec["schema"] = _flatten(mspec["schema"], schemas, frozenset())
    return out


def _strip_required(node: Any, stats: Dict[str, int]) -> Any:
    """去掉对象级 `required` 数组（苍穹把它当布尔关键字读，报 `can not cast to boolean, value: [...]`）。

    为了不丢信息：把"必填"降级写进对应字段的 description（平台/LLM 看描述仍然知道哪个必填）。
    """
    if isinstance(node, list):
        return [_strip_required(x, stats) for x in node]
    if not isinstance(node, dict):
        return node

    req = node.get("required")
    props = node.get("properties")
    if isinstance(req, list) and isinstance(props, dict):
        for name in req:
            p = props.get(name)
            if not isinstance(p, dict):
                continue
            desc = str(p.get("description") or "").strip()
            if "必填" not in desc:
                p["description"] = (desc + "（必填）") if desc else "（必填）"
        stats["required_dropped"] = stats.get("required_dropped", 0) + 1

    out = {k: (v if k == "required" else _strip_required(v, stats)) for k, v in node.items()}
    out.pop("required", None)
    return out


def to_kingdee_profile(doc: Dict[str, Any], server_url: Optional[str] = None) -> Dict[str, Any]:
    """在 3.0.3 基础上再摊平一层：无 $ref / 无 allOf·anyOf·oneOf / 每个节点都有 type。"""
    base = to_openapi_30(doc, server_url=server_url)
    schemas = (base.get("components") or {}).get("schemas") or {}

    methods = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
    flat_paths: Dict[str, Any] = {}
    for path, item in (base.get("paths") or {}).items():
        flat_item: Dict[str, Any] = {}
        for key, val in (item or {}).items():
            if key in methods and isinstance(val, dict):
                flat_item[key] = _flatten_operation(val, schemas)
            elif key == "parameters" and isinstance(val, list):
                flat_item[key] = [
                    ({**p, "schema": _flatten(p["schema"], schemas, frozenset())}
                     if isinstance(p, dict) and isinstance(p.get("schema"), dict) else p)
                    for p in val
                ]
            else:
                flat_item[key] = copy.deepcopy(val)
        flat_paths[path] = flat_item

    out: Dict[str, Any] = {
        "openapi": base["openapi"],
        "info": base["info"],
        "servers": base.get("servers", []),
        "paths": flat_paths,
    }
    if base.get("tags"):
        out["tags"] = base["tags"]
    if schemas:
        out["components"] = {"schemas": {k: _flatten(v, schemas, frozenset({k})) for k, v in schemas.items()}}

    # 最后一刀：去掉对象级 required 数组（个别自研转换器把 required 当布尔读 → cast 异常）
    stats: Dict[str, int] = {}
    out = _strip_required(out, stats)
    if stats:
        out.setdefault("info", {})["x-laya-notes"] = (
            f"已移除 {stats['required_dropped']} 处对象级 required 数组（平台转换器把 required 当布尔读）；"
            "必填信息已写进对应字段 description。"
        )
    return out


def dump_json(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # python -m laya_api.openapi30 [--profile 3.0|kingdee] > openapi.json
    import os
    import sys

    profile = "3.0"
    if "--profile" in sys.argv:
        profile = sys.argv[sys.argv.index("--profile") + 1]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from laya_api.server import app  # type: ignore

    _url = os.getenv("LAYA_OPENAPI_SERVER_URL") or None
    if profile == "kingdee":
        doc = to_kingdee_profile(app.openapi(), server_url=_url)
    else:
        doc = to_openapi_30(app.openapi(), server_url=_url)
    print(dump_json(doc))
