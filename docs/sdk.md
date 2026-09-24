# 调用方 SDK（Java / TypeScript / Python）

三种问法都一样：**给「情境 + 要判断的问题」→ 回「结论 + 把握程度」**。
结论字段：`choice`（选中标签）/ `score`+`level`（期望分与档位）/ `noul`（P(是)）；
`confidence ≥ τ` → `auto=true` 自动处理，否则 `needsReview=true` 转人工。τ 由业务定（默认 0.6）。

| 语言 | 位置 | 依赖 | 实测 |
|---|---|---|---|
| Python | `src/laya_api/client.py`（`LayaClient.choose/rate/yes_no`） | 项目自身 | 已随契约测试 21/21 通过 |
| Java | `sdk/java/src/local/laya/sdk/` | **零第三方依赖**（JDK 11+ `java.net.http`） | javac 17 编译 + 打真实服务跑通 |
| TypeScript | `sdk/ts/laya-client.ts` | **零依赖**（`fetch`） | `node demo.ts` 跑通 + `tsc --strict` 无错 |

## Java

```java
var c = new LayaClient("http://127.0.0.1:8765", System.getenv("LAYA_API_KEY"));

var d = c.choose(Map.of("body", "账单重复扣款，请退款"), "该由哪个团队处理？",
                 Map.of("billing", "退款/计费", "technical", "故障/缺陷"), 0.6);
if (d.auto) dispatch(d.label); else escalateToHuman();

var u = c.rate(state, "紧急程度", List.of("低", "中", "高"), 0.6);   // u.score / u.level
var h = c.yesNo(state, "需要人工介入吗？", 0.6);                    // h.answer / h.probability
```

编译与运行：

```bash
javac -encoding UTF-8 -d out $(find sdk/java/src -name '*.java')
java -Dfile.encoding=UTF-8 -cp out local.laya.sdk.Demo http://127.0.0.1:8765
```

**坑（已踩过并修好）**：JDK `HttpClient` 默认先发明文 HTTP/2 升级（`Connection: Upgrade, HTTP2-Settings`），
uvicorn/h11 不支持 → 服务端直接回 `400 Invalid HTTP request received`。
客户端里已显式 `HttpClient.Version.HTTP_1_1`；自己写客户端时务必照做。
（另：默认字符集请用 UTF-8，否则中文情境会乱码。）

## TypeScript / JavaScript

```ts
import { LayaClient } from './laya-client.ts';   // Node 23 可直接跑 .ts；旧 Node 先用 tsc 编译

const c = new LayaClient('http://127.0.0.1:8765', process.env.LAYA_API_KEY);
const d = await c.choose({ body: '账单重复扣款，请退款' }, '该由哪个团队处理？',
                         { billing: '退款/计费', technical: '故障/缺陷' }, 0.6);
if (d.auto) dispatch(d.label); else escalateToHuman();
```

```bash
node sdk/ts/demo.ts http://127.0.0.1:8765     # 直接跑（Node 23 自带类型剥离）
npx tsc --noEmit -p sdk/ts                     # 类型检查
```

**坑**：Node 的 type-stripping 模式不支持「参数属性」写法（`constructor(public code: string)`）——
客户端里已改成显式字段声明，保证 `node xxx.ts` 直接可跑。

## Python

```python
from laya_api.client import LayaClient
c = LayaClient("http://127.0.0.1:8765", api_key=os.getenv("LAYA_API_KEY"))
d = c.choose({"body": "账单重复扣款，请退款"}, "该由哪个团队处理？",
             {"billing": "退款/计费", "technical": "故障/缺陷"}, tau=0.6)
```

> Python 客户端已支持鉴权：`LayaClient(base_url, api_key=os.getenv("LAYA_API_KEY"))`。

## 鉴权（三端一致）

服务端开 `LAYA_AUTH_MODE=api_key` 后，业务接口需要密钥：
- 默认头：`X-API-Key: <key>`；也接受 `Authorization: Bearer <key>`
- 未带/错误密钥 → `401 {"error":{"code":"UNAUTHORIZED"}}`
- 超限 → `429 {"error":{"code":"RATE_LIMITED"}}`，响应带 `Retry-After`
- `/healthz`、`/docs`、`/wiki`、`/ui` 默认公开；`/v1/status` 可用 `LAYA_AUTH_PROTECT_STATUS=1` 保护

## 错误码（三端都会抛成同名的类型/异常）

`SCHEMA_INVALID(400)` / `UNAUTHORIZED(401)` / `OVER_BUDGET(413)` / `RATE_LIMITED(429)` /
`BUSY(503)` / `MODEL_UNAVAILABLE(503)` / `TIMEOUT(504)` / `INTERNAL(500)`
