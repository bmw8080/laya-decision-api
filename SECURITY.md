# 安全策略

## 报告漏洞

请**不要**用公开 issue 报告安全问题。走 GitHub 的私密漏洞报告
（Security → Report a vulnerability）或直接联系维护者，我们会尽快回复。

请附上：影响范围、复现步骤、最小复现请求、版本/提交号。若涉及密钥泄露，请先自行轮换。

## 部署方的安全基线（本服务默认面向可信内网）

| 项 | 建议 |
|---|---|
| 监听地址 | 默认 `127.0.0.1:8765`。要对外必须前置反代（nginx）并**开启鉴权** |
| 鉴权 | `LAYA_AUTH_MODE=api_key` + `LAYA_API_KEYS`（多把并存便于轮换）；密钥只放环境变量/密钥文件，**绝不进镜像、不进 Git** |
| 限流 | `LAYA_RATE_LIMIT_PER_MIN/_BURST` 按密钥限流；超限返回 429 + `Retry-After` |
| 传输 | 跨机调用请加 TLS 终结（反代层）；本服务自身不带 TLS |
| 暴露面 | `/ui`、`/wiki`、`/docs`、`/redoc`、`/openapi.json` 默认公开（只读文档与本地测试台）；不需要就把它们从 `LAYA_AUTH_PUBLIC_PATHS` 移出或在前置反代上挡住 |
| 数据 | `state` 是业务原文，会进模型输入但**不落盘**；日志不记录请求体（只记方法/路径/状态码） |
| 依赖 | 镜像内 `pip` 元数据保留第三方许可；升级依赖请重跑 `tests/run_contract_tests.py` |

## 已知边界

- 模型输出是概率，不是安全判定。把 `noul`（是否类）用于风控/审核时，请自行标定阈值并保留人工兜底。
- 请求体上限与超时由 `LAYA_DEFAULT_TIMEOUT_MS` / `max_state_chars` 控制；反代层建议再设一层 `client_max_body_size`。
