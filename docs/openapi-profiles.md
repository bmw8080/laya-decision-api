# OpenAPI 三档：3.1 / 3.0 / 扁平档（面向平台导入）

本项目同一套契约对外提供**三个入口**。日常开发用 3.1；企业平台导入大多要 3.0.x；
个别自研 schema 转换器连 3.0 都吃不下，需要再摊平一层。

| 入口 | 版本 | 面向谁 | 这一档做了什么 |
|---|---|---|---|
| `GET /openapi.json` | 由 `LAYA_OPENAPI_VERSION` 决定（默认 **3.1**） | 现代工具链（Swagger UI / ReDoc / 代码生成器） | FastAPI 原生输出，不加工 |
| `GET /openapi-3.0.json` | **固定 3.0.3** | 只认 `3.0.x` 的 API 网关 / API 管理平台 / Apifox 等 | 3.1 → 3.0 降级改写 |
| `GET /openapi-kingdee.json` | **3.0.3 + 彻底扁平** | 自研 `JsonSchema → 参数定义` 转换器（金蝶苍穹等） | 在 3.0.3 基础上再内联 `$ref`、消掉复合关键字、剥掉 `required` |

> `LAYA_OPENAPI_VERSION=3.0` 会让**主档**（`/openapi.json`，连带 `/docs`、`/redoc` 用的那份）也切成 3.0.3；
> `/openapi-3.0.json` 与 `/openapi-kingdee.json` **任何时候都可用**，与这个开关无关。

## 一、3.1 → 3.0 降级改写了什么

都是两个版本之间的真实差异，不是"删掉就完事"：

| 3.1 写法 | 3.0.3 等价写法 |
|---|---|
| `"type": "null"` / `"type": ["string","null"]` | `"nullable": true`（并去掉 `null` 分支） |
| schema 级 `"examples": [...]` | `"example": ...`（取第一个） |
| `"const": v` | `"enum": [v]` |
| `"exclusiveMinimum": 5`（数值） | `"minimum": 5` + `"exclusiveMinimum": true`（同上界） |
| `$ref` 带兄弟键（3.1 允许） | 包成 `allOf: [{"$ref": ...}] + 兄弟键` |
| `prefixItems` / `patternProperties` / `contentMediaType` / `jsonSchemaDialect` / `webhooks` 等 | 移除（3.0 不认识） |

另外补齐 `servers`（可写死成服务真实地址，见下）与缺失的 `operationId`（不少平台导入时必需）。

## 二、扁平档（`/openapi-kingdee.json`）为什么存在

有些平台的 schema 转换器是自研的，容错比规范校验器差得多。实测遇到的三种报错，对应三种处理：

**现象 1｜「无法读取 openapi 信息」/「版本不是 3.0.x」**
→ 版本问题，给 `3.0` 档即可。
平台侧校验器原文：`'3.1.0' does not match '^3\.0\.\d(-.+)?$'`。

**现象 2｜Java 堆栈 `NullPointerException`，出现在 schema 转换器里**
```
kd.ai.gai.core.flow.param.converter.JsonSchemaToParamDefinitionConverter.convertSchema(:150)
  ← fromJsonSchema(:99) ← RestfulApiToolHandler.buildApiOperation(:254)
```
→ 转换器处理不了 `$ref`、`allOf`、`anyOf`、`oneOf`，或遇到**没有 `type` 的 schema 节点**（取到 null 后直接解引用）。
扁平档的处理：

- **内联全部 `$ref`**（带环保护：递归引用用占位对象表示）
- **消掉 `allOf`/`anyOf`/`oneOf`**：`allOf` 合并；联合类型取"信息最全"的一支，语义差异写进 `description`
- **保证每个 schema 节点都有 `type`**（`state: Any` 这类无类型字段会被推断为 `object` 并补 `additionalProperties`）
- 布尔型 `additionalProperties` 归一化成对象；`title` / `description` / `enum` / `example` / `default` 保持原样（数据不做 schema 化）

**现象 3｜`can not cast to boolean, value : ["model","backend"]`**
→ 转换器把**对象级 `required` 数组**当成布尔关键字读了（那个值正是某个 schema 的必填字段名数组）。
扁平档直接**剥掉全部 `required`**，把"必填"信息降级写进字段描述（如 `情境：… （必填）`）——信息不丢，导入不再撞雷。

### 扁平档会损失什么（用之前先知道）

| 损失 | 影响 | 补偿 |
|---|---|---|
| `required` 不再是机器可读的约束 | 平台侧所有参数都显示为可选 | 描述里有「（必填）」；真正的校验仍在服务端（缺字段回 400 `SCHEMA_INVALID`） |
| 联合类型只保留一支 | 少数字段的取值范围变窄 | 差异写在 `description` 里 |
| 递归 `$ref` 用占位对象表示 | 深层结构不完整 | 本服务的契约是浅结构，实际未触发 |

三档都**通过 3.0 专用校验器**（`openapi-spec-validator` 的 `OpenAPIV30SpecValidator`），端点与模型数量一致；
契约测试里有守门断言（扁平档不得残留 `$ref`/`allOf`/`anyOf`/`oneOf`、不得有节点缺 `type`、不得带 `required` 数组）。

## 三、怎么用

**平台能填 URL 就直接填**（推荐，服务升级后文档自动跟着变）：

```
http://<服务地址>:8765/openapi-3.0.json          # 只认 3.0.x 的平台
http://<服务地址>:8765/openapi-kingdee.json      # 自研转换器
```

**平台只支持上传文件就导出**（`LAYA_OPENAPI_SERVER_URL` 可把 `servers` 写死成真实地址，
否则平台导入后调用会打到文档里的默认地址）：

```bash
LAYA_OPENAPI_SERVER_URL=http://10.0.0.5:8765 python -m laya_api.openapi30 > openapi-3.0.json
LAYA_OPENAPI_SERVER_URL=http://10.0.0.5:8765 python -m laya_api.openapi30 --profile kingdee > openapi-kingdee.json
```

## 四、排障顺序（照这个顺序走，别乱猜）

1. 平台报的是「读不到 / 版本不对」→ **版本问题**，用 `/openapi-3.0.json`。
2. 平台给的是 **Java/Python 堆栈**（转换器内部 NPE、类型转换失败）→ **schema 形状问题**，换扁平档。
3. 换了扁平档还报类型转换错 → 把**完整堆栈与报错值**发出来：报错值就是定位线索
   （例如 `["model","backend"]` 直指 `required` 数组）。
4. 本地先自证：`python -m laya_api.openapi30 --profile kingdee | python -c "import json,sys;d=json.load(sys.stdin);print(d['openapi'], len(d['paths']))"`
   应输出 `3.0.3` 与端点数；契约测试里对三档都有断言。
