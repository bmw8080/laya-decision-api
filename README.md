# laya-decision-api

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/bmw8080/laya-decision-api/actions/workflows/ci.yml/badge.svg)](https://github.com/bmw8080/laya-decision-api/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1-6ba539.svg)](contract/decision.v1.schema.json)

把本地 System-1 决策模型（Laya）包成 **一份版本化契约 + 一个 HTTP 服务 + 跨语言 SDK**：
交「情境 + 要判断的问题」，回「结论 + 把握程度」。**离线、零 token、不生成文字**。

> **English** — A production-shaped HTTP service around the Laya local (non-autoregressive,
> System-1) decision model: one versioned contract, one FastAPI service, cross-language SDKs
> (Python / Java / TypeScript), offline OpenAPI 3.1 docs, env-driven auth & rate limiting.
> Apache-2.0. See [docs/sdk.md](docs/sdk.md) and [docs/api-semantics.md](docs/api-semantics.md).
> Tipping is welcome but never required (see 支持这个项目 at the bottom).

## 特性

| | |
|---|---|
| 三种问法 | `choice` 多选一 / `score` 有序程度 / `noul` 是否 —— 对应业务上的「分给谁」「多严重」「要不要」 |
| 概率可编程 | 每次返回概率分布与 `confidence`，阈值由**你的业务**定；服务端不替你拍板 |
| 离线零成本 | 本地推理，不走任何 API；热调用实测 **8–22 ms**（M4 / MLX / multilingual，常驻约 0.7GB） |
| 契约先行 | `pydantic` 模型即真源 → `/openapi.json` 自动生成；文档与实现同源，不会漂移 |
| 跨语言 | Python 语义层 + Java / TypeScript **零依赖** SDK（都对着真实服务跑通） |
| 可运维 | 鉴权（多密钥轮换）、按密钥限流、队列 / 超时 / 缓存全部环境变量控制，`/v1/status` 回显生效配置 |
| 可交付 | 独立单镜像（非 root / HEALTHCHECK / 权重内置 `/models`，也可切成挂载），Linux 容器切 torch 后端 |

## 目录结构

```
laya-decision-api/
├── contract/
│   ├── decision.v1.schema.json      # 契约真源（JSON Schema，版本化的全部字段与语义）
│   └── examples/                    # 可直接回放的请求 / 响应样例
├── src/laya_api/
│   ├── models.py                    # v1 契约模型（pydantic v2）+ ApiError
│   ├── settings.py                  # 全部环境变量 → 配置对象（唯一入口）
│   ├── auth.py                      # 鉴权 + 按密钥令牌桶限流
│   ├── engine.py                    # 后端适配（laya_mlx / hermes_laya / laya_torch）+ 串行队列
│   ├── server.py                    # FastAPI 路由 + 本地托管的 Swagger UI / ReDoc
│   ├── wiki.py                      # /wiki：只渲染 openapi.json 的接口参考
│   ├── ui.py                        # /ui：零构建离线测试台
│   └── static/swagger/              # 随包分发的 swagger-ui / redoc 资源（含许可原文）
├── sdk/{java,ts}/                   # 零依赖跨语言客户端
├── docs/                            # 语义说明、SDK 用法、OpenAPI 三档对照
│   ├── api-semantics.md
│   ├── sdk.md
│   └── openapi-profiles.md
├── tests/                           # 契约 + 语义 + HTTP + 鉴权测试（stdlib，无需 pytest）
└── scripts/                         # 起服务 / 部署 / launchd / 容器
```

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"

bash scripts/run.sh                       # 默认 127.0.0.1:8765（单 worker，必须）
curl -s localhost:8765/healthz
curl -s 'localhost:8765/readyz?warm=1'    # 首次会加载模型（约 1–3 秒）
curl -s localhost:8765/v1/decide -H 'content-type: application/json' \
     -d @contract/examples/decide.request.json
```

浏览器打开 `http://127.0.0.1:8765/` 就是内置测试台（零构建、离线可用）；
`/wiki` 是接口参考，`/docs`（Swagger UI，可 Try it out）与 `/redoc` 是标准 OpenAPI 文档页。
容器部署见「部署 → 容器」。

## 接口

### 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/decide` | 一次决策：给情境与问题，返回结论与概率 |
| `GET` | `/healthz` | 进程存活（不碰模型） |
| `GET` | `/readyz` | 就绪检查；`?warm=1` 先加载模型再回答 |
| `GET` | `/v1/status` | 引擎 / 队列 / 延迟分位 / 计数 + 生效配置（不含密钥） |
| `GET` | `/v1/presets` | 内置问题集名称 |
| `POST` | `/v1/admin/reload` | 重新读取环境变量（密钥 / 限流等），无需重启 |
| `GET` | `/openapi-3.0.json` | OpenAPI **3.0.3** 文档（只认 3.0.x 的平台导入用） |
| `GET` | `/openapi-kingdee.json` | OpenAPI 3.0.3 **扁平档**（`$ref`/`allOf` 全摊平，给自研 schema 转换器） |
| `GET` | `/wiki`、`/docs`、`/redoc`、`/openapi.json`、`/ui` | 文档与测试台（离线） |

字段级说明、示例、错误码以 **`/wiki`**（或 `/openapi.json`）为准 —— 那里由 pydantic 模型自动生成，不会与实现脱节。

### 入参 `POST /v1/decide`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `api_version` | string | 否 | 默认 `"1"` |
| `request_id` | string | 否 | 追踪用，原样回显；不做缓存键 |
| `state` | any | 是 | 待判断的情境：纯文本 / JSON 对象 / messages 数组 |
| `state_format` | `auto\|text\|json\|messages` | 否 | 默认 `auto`（原样交给模型序列化器） |
| `questions` | object | 二选一 | `{qid: {type, instructions, criteria}}`，一次前向可给多个问题 |
| `preset` | string | 二选一 | 内置问题集：`router`（小模型 vs 前沿模型）、`guard`（越狱 / 注入）、`moderation`、`triage`（工单）、`email` |
| `policy.model` | string | 否 | `english` / `multilingual`（默认）/ `typed-decisions` |
| `policy.backend` | string | 否 | `auto`（默认，Apple Silicon 走 mlx）/ `mlx` / `coreml` / `torch` |
| `policy.timeout_ms` | int | 否 | 默认用服务端 `LAYA_DEFAULT_TIMEOUT_MS`（5000）；`0` = 用服务默认 |
| `policy.max_state_chars` | int | 否 | 默认 4000（`0` = 用服务默认），超限截断并回 `warnings` |
| `policy.truncate_state` | bool | 否 | 默认 true；false 时超限直接 `OVER_BUDGET` |
| `policy.max_options` | int | 否 | 默认 20（模型 token 预算的实用上限） |
| `policy.max_queue` | int | 否 | 默认 16，超出回 `BUSY` |
| `policy.return_probabilities` | bool | 否 | 默认 true |

`questions` 的三种类型（校验规则与模型内部一致，接口层提前拦，不让模型抛裸异常）：

```jsonc
{
  "department": {"type": "choice", "instructions": "Which team?",
                 "criteria": {"billing": "payments refunds", "technical": "bugs"}},   // 或 ["billing","technical"]，标签必须唯一
  "urgency":    {"type": "score",  "instructions": "紧急程度", "criteria": ["low","medium","high"]},
  "needs_human":{"type": "noul",   "instructions": "需要人工介入吗", "criteria": {"true":"需要","false":"不需要"}}  // criteria 可省
}
```

### 返回

```jsonc
{
  "api_version": "1",
  "request_id": "uuid",
  "engine": {"model": "multilingual", "backend": "mlx", "pkg": "laya_mlx / laya-mlx 0.2.0 / mlx 0.32.2"},
  "answers": {  // 真实抓包见 contract/examples/decide.response.json
    "department": {"type":"choice","choice":"technical","confidence":0.3657,
                   "probabilities":{"technical":0.5786,"billing":0.0026,"account":0.4188},
                   "action":{"act_probability":1.0}},
    "urgency":    {"type":"score","score":1.0851,"confidence":0.1376,
                   "legend":{"0":"low","1":"medium","2":"high"},
                   "probabilities":{"0":0.1376,"1":0.6397,"2":0.2227},
                   "action":{"act_probability":0.8647}},
    "needs_human":{"type":"noul","noul":0.1363,"confidence":0.8637,
                   "action":{"act_probability":0.8649}}
  },
  "usage": {"latency_ms": 17.2, "queue_wait_ms": 0.4, "input_tokens": 32, "output_tokens": 0, "cold_start": false},
  "warnings": ["state_truncated"]
}
```

### 错误码

| code | HTTP | 何时 |
|---|---|---|
| `SCHEMA_INVALID` | 400 | 字段缺失 / 类型错 / choice 标签重复等 |
| `UNAUTHORIZED` | 401 | 未带或错误的密钥（开启 `LAYA_AUTH_MODE=api_key` 时） |
| `OVER_BUDGET` | 413 | 状态或选项超 token 预算（不截断时） |
| `RATE_LIMITED` | 429 | 超出该密钥的速率上限；响应带 `Retry-After` |
| `BUSY` | 503 | 队列满 |
| `MODEL_UNAVAILABLE` | 503 | 后端 / 权重不可用 |
| `TIMEOUT` | 504 | 超 `timeout_ms`（底层推理仍在跑，见「工程约束」） |
| `INTERNAL` | 500 | 其它 |

三条铁律：

1. **概率必给**（`return_probabilities=true` 时）。服务端不替业务拍板阈值。
2. **「不确定」不是错误**：用低 `confidence` 表达，不抛异常、不回空值。
3. **错误分层可编程**：按上表分支即可，不需要解析文本。

## 三种问法怎么用

| 语义 | 一句话 | 典型业务 | 问法 |
|---|---|---|---|
| **选择类** | 这属于哪一类 / 该给谁 | 工单分派、内容分类、模型路由、打标签 | `choose(...)` / `type=choice` |
| **程度类** | 有多严重 / 打几分 | 优先级、紧急度、风险分级、满意度 | `rate(...)` / `type=score` |
| **是非类** | 要不要 / 是不是 | 是否转人工、是否放行、是否违规 | `yes_no(...)` / `type=noul` |

- 读结果只看两项：**结论**（`choice` / `score`+`legend` / `noul`）与 **`confidence`**（≥τ 自动处理，<τ 转人工）。
- 完整语义说明（选型、误用、阈值标定建议）：**[docs/api-semantics.md](docs/api-semantics.md)**。

```python
from laya_api.client import LayaClient

c = LayaClient("http://127.0.0.1:8765", api_key=None)   # 开了鉴权就传密钥
d = c.choose({"body": "账单重复扣款，请退款"}, "该由哪个团队处理？",
             {"billing": "退款/计费", "technical": "故障/缺陷"}, tau=0.6)
if d.auto:
    dispatch(d.label)          # conf ≥ 0.6，自动分派
else:
    escalate_to_human()        # 把握不足，转人工
```

## 客户端 SDK

| 语言 | 位置 | 依赖 | 验证方式 |
|---|---|---|---|
| Python | `src/laya_api/client.py`（`choose` / `rate` / `yes_no` + `ThresholdRouter` + `InProcessEngine`） | 项目自身（httpx） | 随全套测试通过 |
| Java | `sdk/java/` | **零依赖**（JDK 11+ `java.net.http`，自带极简 JSON） | `javac 17` 编译 + 打真实服务跑通 |
| TypeScript | `sdk/ts/` | **零依赖**（`fetch`） | `node demo.ts` 跑通 + `tsc --strict` 无错 |

```bash
javac -encoding UTF-8 -d out $(find sdk/java/src -name '*.java')
java -Dfile.encoding=UTF-8 -cp out local.laya.sdk.Demo http://127.0.0.1:8765

node sdk/ts/demo.ts http://127.0.0.1:8765
npx -p typescript@5.9.2 tsc --noEmit -p sdk/ts
```

用法、鉴权传参，以及两个已踩的坑（Java 必须显式 HTTP/1.1、Node 类型剥离不支持参数属性）见
**[docs/sdk.md](docs/sdk.md)**。

## 运维与安全

全部开关见 **[`.env.example`](.env.example)**（一处清单，容器 / 前台通用）；`GET /v1/status` 回显生效配置
（密钥只显示数量），改完可 `POST /v1/admin/reload` 热生效，无需重启。

### 鉴权

| 变量 | 默认 | 说明 |
|---|---|---|
| `LAYA_AUTH_MODE` | `off` | `off`（本机 / 可信内网）或 `api_key` |
| `LAYA_API_KEYS` | 空 | 多把并存便于轮换：`key-a,key-b`；只放环境 / 密钥文件，**绝不进镜像** |
| `LAYA_AUTH_HEADER` | `X-API-Key` | 也接受 `Authorization: Bearer <key>` |
| `LAYA_AUTH_PROTECT_STATUS` | `0` | `1` 时 `/v1/status` 也要密钥 |
| `LAYA_AUTH_PUBLIC_PATHS` | healthz/readyz/docs/redoc/wiki/ui/openapi/static | 公开路径白名单 |
| `LAYA_RATE_LIMIT_PER_MIN` / `_BURST` | `0`（不限流） | 按密钥令牌桶限流，超限 `429` + `Retry-After` |

实测（独立实例，`api_key` + 3/分钟）：健康检查 200；无密钥 401；错密钥 401；正确密钥 200；
超出后 `429` 且带 `Retry-After: 19`；错误体 `{"error":{"code":"RATE_LIMITED","details":{"retry_after_s":18.49}}}`。
密钥用 `hmac.compare_digest` 比较（防时序侧信道），日志与状态里只出现密钥的 SHA-256 前 8 位指纹。

### 性能

| 变量 | 默认 | 说明 |
|---|---|---|
| `LAYA_MAX_QUEUE` | 16 | 排队上限；满了直接 `BUSY`（让调用方退避，不无限堆积） |
| `LAYA_DEFAULT_TIMEOUT_MS` | 5000 | 请求未指定时的默认超时 |
| `LAYA_PREFIX_CACHE` | 1 | 缓存问题前缀：20 次同问题不同情境实测 13.20 → **12.41 ms**（约 6%） |
| `LAYA_BUSY_RETRY_AFTER_S` | 1 | `BUSY` / `429` 的 `Retry-After` |
| `LAYA_WARM_ON_START` | 1 | 启动即加载模型（首调用不等冷启动） |

实测延迟（M4 / MLX / multilingual，常驻）：热调用 **8–22 ms**（p50 8.45），冷启首调 35–58 ms（含加载 480 ms）；
串行队列下 `queue_wait` 0.01–0.06 ms。

**单进程串行是刻意设计**：MLX 单设备，多 worker 会各自加载约 0.7GB 且互相抢卡；批量要走「一次前向多问题」而不是并发。
要横向扩：起 N 个进程（各约 0.7GB）监听不同端口，前置 nginx `least_conn` 轮询即可 —— 服务本身无状态。

## 部署

### 本机运行（macOS）

**调试期不必常驻** —— 直接前台起，Ctrl-C 停，最省事：

```bash
bash scripts/run.sh                      # 前台起服务（默认 127.0.0.1:8765；Ctrl-C 停）
curl -s 'http://127.0.0.1:8765/readyz?warm=1'
# 想后台跑又不装服务（临时）：nohup bash scripts/run.sh > /tmp/laya-api.log 2>&1 &
```

要低延迟常开（反复调试/给别的系统联调）才装成 LaunchAgent：

```bash
bash scripts/install-service.sh           # 部署 + 安装 LaunchAgent（常驻）
bash scripts/deploy.sh                    # 改完源码后同步运行副本 + 重启
bash scripts/uninstall-service.sh         # 卸载（回滚）
# 日志：~/Library/Logs/laya-decision-api/service.{out,err}.log
```

实测验收：`/healthz` → `{"status":"ok","ready":true,...}`；`/readyz?warm=1` → `loaded:["mlx/multilingual"]`；
连发多次 `queue_wait` 0.01–0.04 ms；choice 标签重复 → HTTP 400 `SCHEMA_INVALID`。

> **launchd 读不到外置卷（实测踩过）**：若源码放在可移动卷 / 外置盘，macOS 的用户级 LaunchAgent
> 没有该卷的访问权限，直接跑会报 `Operation not permitted`。因此常驻服务跑的是
> **home 下的运行副本**（`~/Library/Application Support/laya-decision-api`，由 `scripts/deploy.sh` 同步）。
> 改完源码务必 `bash scripts/deploy.sh`，否则跑的还是旧副本；前台调试不受此限制。

### 容器（Linux，独立镜像）

两级构建 + 非 root + HEALTHCHECK + 入口自检 + 国内镜像源；laya 作为**独立镜像**运行，不塞进业务镜像。

```
builder(python:3.12-slim) ──pip→ /install ──┐
                                            ├─► runner ──► 一个镜像
源码 src/ + contract/ + entrypoint ─────────┘   非 root / HEALTHCHECK / 权重内置 /models
```

**基础镜像怎么选**（决定了构建期要不要下 torch）：

| 基础镜像 | 构建期动作 | 镜像体积 | 适用 |
|---|---|---|---|
| `python:3.12-slim-bookworm`（默认） | 需 `pip install torch`（CPU 版约 200MB） | 约 1GB | 构建机能访问 torch 索引 |
| 官方 `pytorch/pytorch:<ver>-runtime`（推荐） | torch 已预装，**自动跳过**（`import torch` 探测） | 约 2–3GB | 构建机网络差 / 想少一处失败点 |
| 有网机器构建后 `docker save` → 服务器 `docker load` | 服务器完全离线 | 同上 | 内网 / 离线交付 |

```bash
# 权重打进镜像（单文件交付，默认）：先放进构建上下文 weights/
bash scripts/fetch-weights.sh ./weights             # ModelScope 国内直连 644MB；已有权重直接 cp 进 weights/multilingual 也行
bash scripts/docker-build.sh laya-decision-api:uat  # 默认清华 PyPI + torch CPU 索引
cp .env.docker.example .env.docker
bash scripts/docker-run.sh laya-decision-api:uat    # 镜像自带权重，无需挂载；只监听 127.0.0.1:8765

# 验证
docker run --rm laya-decision-api:uat python -c "import laya, fastapi, uvicorn; print('deps ok')"
curl -s 'localhost:8765/readyz?warm=1'              # 期望 loaded:["torch/multilingual"]
```

**权重进不进镜像两种形态**（按交付方式选）：

| 形态 | 做法 | 结果 |
|---|---|---|
| 单文件交付（默认） | 构建前把权重放进 `weights/`（`COPY weights/ /models/`） | `docker load` 后直接 `docker run` 就能起，不依赖宿主目录；镜像 +644MB |
| 瘦身 / 权重外置 | `weights/` 只留 `.gitkeep` 再构建 | 镜像小 644MB；运行时挂载：`LAYA_MOUNT_MODELS=1 bash scripts/docker-run.sh <tag>` |

> 镜像内权重目录是 `/models/<model>`（默认 `/models/multilingual`）。Dockerfile 里**没用 `VOLUME` 声明**
> —— 声明了会在运行时生成匿名卷遮蔽镜像内的权重，反而变成"看起来没权重"。

### 用现成镜像（Docker Hub）

不想自己构建就直接拉（镜像自带权重，起容器即用）：

```bash
docker pull bmw8080/laya-decision-api:1.0.1
docker run -d --name laya-api -p 8765:8765 \
  -e LAYA_AUTH_MODE=api_key -e LAYA_API_KEYS=替换成你的密钥 \
  bmw8080/laya-decision-api:1.0.1
curl -s 'http://127.0.0.1:8765/readyz?warm=1'      # 期望 loaded:["torch/multilingual"]
```

- **锁版本**：`1.0.1` 这类具体标签便于回溯；`latest` 跟随最新发布。
- **架构**：发布的是 `linux/amd64`（服务器主流）。arm64 想本地跑，用源码形态 `bash scripts/run.sh`（走 MLX，比容器快得多）；
  需要 arm64 镜像就在 arm64 机器上 `bash scripts/docker-build.sh` 自建，Dockerfile 架构中立。
- **不含密钥**：镜像里不烤鉴权密钥，靠运行期 `-e` 注入；权重已打进镜像，无需挂载。

**国内拉不动 Docker Hub 时**——换国内加速前缀，镜像字节与官方一致：

```bash
# 两条都实测可用（2026-09-24 复核：镜像摘要与 Docker Hub 完全相同）
docker pull docker.1panel.live/bmw8080/laya-decision-api:1.0.1
docker pull docker.1ms.run/bmw8080/laya-decision-api:1.0.1     # 需要 token，docker CLI 自动处理

docker tag docker.1panel.live/bmw8080/laya-decision-api:1.0.1 bmw8080/laya-decision-api:1.0.1
docker run -d --name laya-api -p 8765:8765 \
  -e LAYA_AUTH_MODE=api_key -e LAYA_API_KEYS=替换成你的密钥 \
  bmw8080/laya-decision-api:1.0.1
```

- 加速站是第三方公益镜像，随时可能失效或加白名单限制。反例：`docker.m.daocloud.io` 明确拒绝拉取本项目镜像
  （用它拉 `python` 这类基础镜像是另一回事，**不要混用**）；失效就换下一条。
- 拉完想确认拉到的确实是官方那份，核对镜像摘要：`1.0.1` / `latest` 当前为
  `sha256:64f5e6c38415ab27…`（linux/amd64、15 层、约 922 MB）。
  查法：`docker pull` 的输出里会打印 Digest，或 `docker image inspect --format '{{index .RepoDigests 0}}' bmw8080/laya-decision-api:1.0.1`。

### 给只认 OpenAPI 3.0 的平台导入

> 三档（3.1 / 3.0 / 扁平档）怎么选、各自踩过什么坑，见 **[docs/openapi-profiles.md](docs/openapi-profiles.md)**。

FastAPI 原生产出 **OpenAPI 3.1.0**，而部分企业 API 平台（API 网关 / API 管理 / Apifox 等）只认 **3.0.x**，
导入时会报「无法读取 openapi 信息 / 版本不是 3.0.x」。本服务提供三个入口：

| 入口 | 版本 | 用途 |
|---|---|---|
| `GET /openapi.json` | 由 `LAYA_OPENAPI_VERSION` 决定（默认 `3.1`） | 默认 3.1；设成 `3.0` 后连同 `/docs`、`/redoc` 一起切成 3.0.3 |
| `GET /openapi-3.0.json` | **固定 3.0.3** | 给只认 3.0.x 的平台导入（推荐直接用这个 URL） |
| `GET /openapi-kingdee.json` | **3.0.3 + 彻底扁平** | 自研 schema 转换器（如金蝶苍穹）会因 `$ref`/`allOf`/`anyOf` 抛 NPE，这一档全部摊平 |
| `python -m laya_api.openapi30 > openapi-3.0.json` | 3.0.3 | 平台只支持"上传文件"时，导出文件再上传 |
| `python -m laya_api.openapi30 --profile kingdee > openapi-kingdee.json` | 3.0.3 扁平 | 同上，但要喂给自研转换器时用这一档 |

降级做了这些改写（都是 3.1 → 3.0 的差异）：`type: "null"` → `nullable: true`、schema 级
`examples: [...]` → `example:`、`const` → `enum`、数值型 `exclusiveMinimum/Maximum` → 布尔开关 +
`minimum/maximum`、`$ref` 带兄弟键 → `allOf` 包装、删除 3.0 不认识的关键字
（`prefixItems`/`patternProperties`/`contentMediaType`…）与顶层 `jsonSchemaDialect`/`webhooks`；
并补齐 `servers` 与缺失的 `operationId`。

```bash
# 直接给平台填这个地址
http://<服务地址>:8765/openapi-3.0.json

# 或导出文件上传（servers 想写死成真实地址就设 LAYA_OPENAPI_SERVER_URL）
LAYA_OPENAPI_SERVER_URL=http://10.0.0.5:8765 python -m laya_api.openapi30 > openapi-3.0.json
```

> 校验口径：本仓库的契约测试里用 `openapi-spec-validator` 的 **3.0 专用校验器**验过 ——
> 未降级的 3.1 文档会被它拒（`'3.1.0' does not match '^3\.0\.\d(-.+)?$'`，即平台报的那句），
> 降级后的 3.0.3 文档通过。

**扁平化档（`/openapi-kingdee.json`）解决的是另一类问题**：某些自研转换器（金蝶苍穹
`JsonSchemaToParamDefinitionConverter.convertSchema` 实测）遇到 `$ref`、`allOf`、`anyOf`、或**没有 `type`
的 schema 节点**会直接 `NullPointerException`。这一档在 3.0.3 基础上再摊平：

- **内联全部 `$ref`**（带环保护，递归引用用占位对象表示）
- **消掉 `allOf`/`anyOf`/`oneOf`**：`allOf` 合并；联合类型取"信息最全"的一支，语义差异写进 `description`
- **每个 schema 节点都带 `type`**（原来 `state: Any` 这类无 type 的字段会被推断成 `object` 并补 `additionalProperties`）
- 布尔型 `additionalProperties` 归一化为对象；`title`/`description`/`enum`/`example`/`default` 等仍保留（数据原样，不做 schema 化）
- 仍是合法 3.0.3（过了 3.0 专用校验器），端点与模型一个不少

### 构建期参数（`--build-arg`）与运行期环境变量

**优先级：运行期 `-e` / `--env-file` > 构建期 `--build-arg` > Dockerfile 默认值。**
所以端口、鉴权密钥这类"部署时才定"的东西，优先用运行期注入，不必重建镜像。

构建期可赋值的参数（全部有默认值，见 Dockerfile 顶部参数表）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `BASE_IMAGE` / `RUN_BASE_IMAGE` | `python:3.12-slim-bookworm` | 基础镜像（要预装 torch 就换 `pytorch/pytorch:*`） |
| `APP_DIR` / `MODELS_DIR` | `/app` / `/models` | 镜像内应用目录 / 权重目录 |
| `LAYA_RUN_USER` / `LAYA_RUN_UID` / `LAYA_RUN_GID` | `app` / `1001` / `1001` | 运行用户（非 root） |
| `LAYA_API_HOST` / `LAYA_API_PORT` | `0.0.0.0` / `8765` | 监听地址 / 端口 |
| `LAYA_ENGINE` / `LAYA_MODEL` / `LAYA_BACKEND` | `laya_torch` / `multilingual` / `auto` | 引擎 / 模型 / 后端 |
| `LAYA_MODEL_DIR` | `${MODELS_DIR}/${LAYA_MODEL}` | 权重目录（留空即用默认） |
| `LAYA_WARM_ON_START` / `LAYA_PREFIX_CACHE` | `1` / `1` | 启动预热 / 前缀缓存 |
| `LAYA_MAX_QUEUE` / `LAYA_DEFAULT_TIMEOUT_MS` / `LAYA_BUSY_RETRY_AFTER_S` | `16` / `5000` / `1` | 队列与超时 |
| `LAYA_MAX_STATE_CHARS` / `LAYA_MAX_OPTIONS` | `4000` / `20` | 体积上限 |
| `LAYA_AUTH_MODE` / `LAYA_API_KEYS` / `LAYA_AUTH_HEADER` / `LAYA_AUTH_PROTECT_STATUS` | `off` / 空 / `X-API-Key` / `0` | 鉴权 |
| `LAYA_AUTH_PUBLIC_PATHS` / `LAYA_RATE_LIMIT_PER_MIN` / `LAYA_RATE_LIMIT_BURST` | 见 Dockerfile | 公开路径 / 限流 |
| `PIP_INDEX_URL_BUILD` / `TORCH_INDEX_URL` / `DEBIAN_MIRROR` / `PIP_FLAGS` / `LAYA_PIP_SPEC` | 见 Dockerfile | 构建源与开关 |

```bash
# 例：换个端口与运行用户，同时把鉴权打开（密钥建议运行时给，别烤进镜像）
LAYA_API_PORT=9000 LAYA_RUN_UID=2000 LAYA_AUTH_MODE=api_key \
  bash scripts/docker-build.sh laya-decision-api:1.0.1
```

⚠️ **密钥不要用 `--build-arg` 烤进镜像**：`--build-arg LAYA_API_KEYS=xxx` 会把值固化进镜像层
（`docker history` / `docker inspect` 可见，推到镜像仓后收不回来）。正确做法是运行时注入：

```bash
# .env.docker 里写 LAYA_AUTH_MODE=api_key / LAYA_API_KEYS=xxx，然后
bash scripts/docker-run.sh laya-decision-api:1.0.1          # 走 --env-file
# 或临时指定
docker run -d -e LAYA_API_KEYS=xxx -e LAYA_AUTH_MODE=api_key ... laya-decision-api:1.0.1
```

`scripts/docker-build.sh` 会把上面这些 `LAYA_*`（以及 `APP_DIR`/`MODELS_DIR`/`LAYA_RUN_*`）
**设了的环境变量自动透传**成 `--build-arg`，并在日志里逐条打印（密钥显示为 `***`）。

换基础镜像：`bash scripts/docker-build.sh <tag> --build-arg BASE_IMAGE=… --build-arg RUN_BASE_IMAGE=…`
（标签请先在构建机 `docker pull` 确认存在）。

| 内容 | 是否进镜像 | 说明 |
|---|---|---|
| `src/`、`contract/`、`docker-entrypoint.sh` | 是 | 服务本体与契约 |
| fastapi / uvicorn / pydantic / httpx | 是 | 见 `requirements-docker.txt` |
| torch(CPU) + 上游 `laya` | 是 | 容器必须用 torch 后端：MLX 是 macOS + Metal 专属 |
| 644MB 权重 | **是（默认，构建时 COPY）** | 放 `weights/` 即打进镜像（单文件交付）；不想带就别放，运行时 `-v /opt/laya-models:/models:ro` 挂载 |

反代：nginx **保留路径**（`proxy_pass http://127.0.0.1:8765;`，不带尾斜杠），`proxy_read_timeout` 给足。

### 架构（x86_64 / arm64）与跨机交付

**镜像架构 = 构建机架构**。Apple Silicon 上构建出来的是 linux/arm64，拷到 x86_64 服务器会
`exec format error`。三条路，按场景选：

| 场景 | 做法 | 代价 |
|---|---|---|
| 有 x86_64 的 Linux（含 VM） | 直接在那台机器上构建 | 最快，无模拟层（**推荐**）|
| 只有 arm64 Mac | `PLATFORM=linux/amd64 bash scripts/docker-build.sh <tag>` | 需 buildx + QEMU 模拟，torch 层可能十几分钟起 |
| 构建机与目标机都不能联网 | 有网机器构建 → `docker save` → 拷贝 → `docker load` | 传输 1–2GB 压缩包 |

依赖的架构支持（已核对 PyPI/Docker Hub 元数据，非推测）：

| 组件 | linux/amd64 | linux/arm64 |
|---|---|---|
| `torch`（CPU） | `manylinux_2_28_x86_64` wheel ✔ | `manylinux_2_28_aarch64` wheel ✔ |
| 上游 `laya` | `py3-none-any`（纯 Python，架构无关）✔ | 同左 ✔ |
| `tokenizers` / `numpy` / `safetensors` | 两架构均有 manylinux wheel ✔ | ✔ |
| `python:3.12-slim-bookworm`（默认基础镜像） | multi-arch manifest ✔ | ✔ |

> 服务器 CPU 需支持 **AVX2**（torch 官方 wheel 的编译前提）：`lscpu | grep -o avx2`。
> 老 CPU 上要换源码编译版 torch。

**torch 轮子从哪装（两个架构都是：用 PyTorch 官方 CPU 索引，别用 PyPI）**：

| `TORCH_INDEX_URL` | 结果 |
|---|---|
| `https://download.pytorch.org/whl/cpu`（默认） | 装纯 CPU 版，无 CUDA 依赖 |
| `https://mirror.sjtu.edu.cn/pytorch-wheels/cpu/` | **国内推荐**。同样是 PEP 503 索引、同样只有 CPU 版；实测官方索引的索引页能打开，但**真正的轮子托管在 `download-r2.pytorch.org`，该主机在国内不可达**（构建会报 `Could not find a version that satisfies the requirement torch (from versions: none)`） |
| PyPI / PyPI 国内镜像 | **会拖 `nvidia-*` 整套 CUDA 包**（实测：aarch64 上装 torch 时 pip 开始下载 `nvidia-cudnn-cu13` 等；x86_64 同理），磁盘和下载量都翻好几倍 —— 不要用 |

> 该索引在国内偶发连接不稳（`Temporary failure in name resolution`），Dockerfile 里三处 pip 都加了
> `--retries 10 --timeout 60` 兜底。

**跨架构构建（在 arm64 机器上产出 x86_64 镜像）**：

```bash
# 1) 先注册 QEMU 处理器（只需一次；Docker Hub 不通就用镜像站前缀）
docker run --privileged --rm docker.m.daocloud.io/tonistiigi/binfmt --install amd64

# 2) 跨架构构建（QEMU 模拟，慢；--no-compile 跳过字节码编译可明显提速）
PLATFORM=linux/amd64 PIP_FLAGS=--no-compile \
  BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim-bookworm \
  RUN_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim-bookworm \
  bash scripts/docker-build.sh laya-decision-api:1.0.1-amd64
```

实测数据（arm64 机器上跨构建 x86_64）见下方「交付记录」；构建耗时受 QEMU 与网络影响大。

> 若 `deb.debian.org` 在你的网络里被中间设备干扰（构建时报 `Clearsigned file isn't valid, got 'NOSPLIT'`），
> 用 `DEBIAN_MIRROR` 换源：`bash scripts/docker-build.sh <tag> --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn`
> （`scripts/docker-build.sh` 已默认传清华源，`DEBIAN_MIRROR="" ` 可关掉走官方源）。

**一条命令打包（在 Ubuntu VM / x86 构建机上跑）**：

```bash
bash scripts/docker-ship.sh laya-decision-api:1.0.1 ./dist
# 顺带把 644MB 权重也打包（目标服务器不能上 ModelScope 时）：
WITH_WEIGHTS=1 bash scripts/docker-ship.sh laya-decision-api:1.0.1 ./dist
```

它会依次做：环境自检（架构 / docker / buildx / 磁盘）→ 构建 → **镜像内真实 import 自检** →
`docker save` + gzip + SHA-256 → 打印服务器侧命令（校验 → `docker load` → 权重 → 起服务 → 健康检查）。

**目标服务器上**：

```bash
sha256sum -c laya-decision-api-1.0.1-amd64.tar.gz.sha256
docker load < laya-decision-api-1.0.1-amd64.tar.gz
docker image inspect laya-decision-api:1.0.1 --format '{{.Os}}/{{.Architecture}}'   # 应为 linux/amd64
bash scripts/fetch-weights.sh /opt/laya-models     # 或解包一起拷过来的权重包
cp .env.docker.example .env.docker && bash scripts/docker-run.sh laya-decision-api:1.0.1
curl -s 'http://127.0.0.1:8765/readyz?warm=1'      # 期望 loaded:["torch/multilingual"]
```

> **哪些是实测、哪些不是**（避免误读）：镜像构建、`docker load`、容器内权重加载与一次真实判定，
> 都已在 arm64 VM 上跑过（跨架构构建成 linux/amd64，QEMU 模拟执行），见下方「交付记录」；
> 但 **QEMU 下的耗时数字不代表 x86_64 原生性能**（模拟层慢两个数量级）。
> 本机（Apple Silicon，无 Docker）只跑了前台 / launchd 形态。

### 后端对照（同一份 safetensors 权重，各形态共用）

| 形态 | `LAYA_ENGINE` | 依赖 | 说明 |
|---|---|---|---|
| Mac 常驻（快） | `laya_mlx`（默认） | `laya-mlx` + `mlx` | Metal 加速，热调用 8–9 ms |
| Linux 容器 | `laya_torch` | `torch` + 上游 `laya` | 无 Metal |
| 与 Hermes 同源 | `hermes_laya` | `hermes-laya[mlx]` | 需要与 Hermes 工具 / context engine 走同一代码路径时 |

**与 Hermes 的关系：不必须。** 默认的 `laya_mlx` 是上游普通 pip 包，实测直连时**零 Hermes 模块导入**
（契约测试里有一条「独立模式未导入任何 Hermes 模块」专门守这个）。接 Hermes 只是额外能力。

## 测试

不依赖 pytest（stdlib 即可跑）：

```bash
python tests/run_contract_tests.py
```

覆盖：契约校验与错误码、超预算、golden 用例、同 state 连打 10 次的稳定性与概率波动、
HTTP 端点（httpx `ASGITransport`）、鉴权与限流、离线文档守门（`/docs`、`/redoc` 不得引用 CDN；
`/wiki` 只能渲染 OpenAPI，不许混进 README 内容）、OpenAPI 三档的守门断言。

**没装推理后端时**（CI / 只想验契约）：依赖模型前向的用例自动 `SKIP`，其余全跑 —
实测 `10 passed, 0 failed, 12 skipped`，退出码 0；装好后端则 `21 passed, 0 failed`。

## 工程约束与设计取舍

- **契约是兼容性红线**：破坏性改动必须新开 `v2`，不在 v1 里改字段含义。
- **序列预算 512 token**（头部 192）。选项过多会被预算顶掉 → 接口层返回 `OVER_BUDGET`，而不是让模型抛 `ValueError`。
- **单设备串行**：`get_agent` 按 `(backend, model)` 缓存但不做串行 → 本服务的 worker 单线程串行执行；要吞吐就走多问题一次前向或横向扩进程。
- **常驻内存约 0.7GB**（multilingual fp16），加载 0.46–0.73 秒（打本地权重补丁后；未打补丁会联网校验，实测卡 150s）。
- **超时语义**：MLX 推理无法中途取消。超时只保证调用方拿到 504，底层那次前向会跑完再释放 worker（响应带 `inference_still_running` 警告）。
- **概率校准 ≠ 准确率**：`confidence` 是模型自校准值，业务阈值 τ 必须用自己的样本标定。
- **不替调用方拍板**：服务端只回概率与置信度；低置信度回退大模型是可选的 `ThresholdRouter`，默认不介入。

## 排障

| 现象 | 先看 |
|---|---|
| `/readyz` 里 `ready=false` | 模型是否加载失败：看服务日志与 `/v1/status` 的 `engine` 段 |
| 调用报 `MODEL_UNAVAILABLE` | `LAYA_ENGINE` 对应的包是否装了（`laya-mlx`/`mlx` 或 `torch`/`laya`）；权重目录是否存在 |
| 首个请求特别慢 | 冷启动；开 `LAYA_WARM_ON_START=1` 或先打一次 `/readyz?warm=1` |
| `BUSY` / `429` | 队列或速率上限；按 `Retry-After` 退避，不要立即重试 |
| 容器里报后端不可用 | 容器必须 `LAYA_ENGINE=laya_torch`（Linux 没有 Metal） |
| 改了源码行为没变 | 常驻跑的是 home 运行副本，忘了 `bash scripts/deploy.sh` |

## 支持这个项目

这个项目是业余时间做的，能帮到你我就挺高兴。如果它确实省了你的时间，欢迎扫码打赏一杯咖啡 ☕

<img src="docs/assets/donate-wechat.jpg" alt="微信打赏" width="240">

> 打赏完全自愿：**不影响任何功能、issue 优先级或回复速度**。有问题照常提 issue 就好。

## 贡献

欢迎提 issue / PR。约定见 **[CONTRIBUTING.md](CONTRIBUTING.md)**，行为准则见 **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**，
安全问题走 **[SECURITY.md](SECURITY.md)**（不要开公开 issue）。变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 交付记录（实测）

在 arm64 Ubuntu VM（2 vCPU / 4GB，Docker 28.0.4 + buildx 0.22，已注册 QEMU amd64）上跨架构构建 `linux/amd64`：

| 项 | 结果 |
|---|---|
| 构建耗时 | 构建缓存命中约 7 分钟；冷缓存（要下 torch 轮子）25–35 分钟 |
| 镜像 | 解包 1.76GB（15 层）；`docker save \| gzip` 后交付包 902MB |
| 镜像架构 | `linux/amd64`（构建机是 arm64，靠 `PLATFORM=linux/amd64` + QEMU） |
| 容器内自检 | `/healthz` 200；权重加载成功 `loaded:["laya_torch/multilingual"]` |
| 容器内真判定 | 返回 `choice` + 概率分布 + `confidence`，`request_id` 原样回显 |
| 三档文档 | `/openapi.json` 3.1 ｜ `/openapi-3.0.json` 3.0.3 ｜ `/openapi-kingdee.json` 3.0.3 扁平（`required` 残留 0） |
| 交付包校验 | `sha256sum -c` 通过，跨机二次校验一致 |

> **QEMU 下的耗时不代表 x86_64 原生性能**：模拟层里模型加载 46–50 秒、单次判定约 12 秒；
> 同一份权重在 arm64 宿主（MLX 形态）上热调用是 8–22 毫秒。要在 x86 上看真实性能，只能在 x86 上原生跑。

## 许可证

[Apache License 2.0](LICENSE)。随包分发的第三方组件（swagger-ui-dist、redoc）许可原文见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 `src/laya_api/static/swagger/`。
Laya 决策模型本体是独立上游项目，**权重不随本仓库分发**。
