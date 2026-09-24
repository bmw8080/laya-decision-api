# 更新日志

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。契约变更请看 `contract/` 的版本后缀。

## [1.0.1] - 2026-09-24

### 新增
- **OpenAPI 3.0.3 扁平化档**（`GET /openapi-kingdee.json`，或 `python -m laya_api.openapi30 --profile kingdee`）：
  针对金蝶苍穹 `JsonSchemaToParamDefinitionConverter` 的 NPE（实测报错 `convertSchema:150`）——内联全部 `$ref`、
  消掉 `allOf`/`anyOf`/`oneOf`、保证每个 schema 节点都有 `type`、布尔 `additionalProperties` 归一化；
  仍通过 3.0 专用校验器，端点/模型不丢。契约测试加了守门断言（不得残留 `$ref`/`allOf`/`anyOf`/`oneOf`、不得有节点缺 `type`）。
- **苍穹档进一步剥掉对象级 `required` 数组**：实测苍穹转换器把 `required` 当布尔关键字读，报
  `can not cast to boolean, value : ["model","backend"]`（值正是 `EngineInfo` 的必填数组）；
  改为把"必填"降级写进字段描述（如「情境：… （必填）」）——信息不丢、导入不再撞雷。契约测试加断言：苍穹档内 `required` 残留必须为 0
- **OpenAPI 3.0.3 导出**（给只认 3.0.x 的平台导入，如 API 网关 / API 管理 / Apifox）：
  - `GET /openapi-3.0.json` 恒为 3.0.3；`LAYA_OPENAPI_VERSION=3.0` 可把 `/openapi.json`（含 `/docs`、`/redoc`）整体切成 3.0.3
  - `python -m laya_api.openapi30 > openapi-3.0.json` 导出文件（`LAYA_OPENAPI_SERVER_URL` 可写死 servers 地址）
  - 降级改写：`type:"null"`→`nullable`、schema 级 `examples`→`example`、`const`→`enum`、数值型
    `exclusiveMinimum/Maximum`→布尔开关+`minimum/maximum`、`$ref` 带兄弟键→`allOf`、剔除 3.0 不认识的关键字与 `webhooks`/`jsonSchemaDialect`，并补 `servers`/`operationId`
  - 契约测试用 `openapi-spec-validator` 的 **3.0 专用校验器**验证：未降级的 3.1 文档被拒（复现平台报错），降级后通过

### 新增
- `scripts/docker-ship.sh`：一条命令打包离线交付物（环境自检 → 构建 → 镜像内 import 自检 → `docker save` + SHA-256 → 打印服务器侧命令），支持 `WITH_WEIGHTS=1` 连权重一起打

### 修复
- 容器脚本里 `$VAR` 紧跟中文被 bash 当成变量名的一部分（`set -u` 下报 unbound variable）：`docker-build.sh` / `docker-entrypoint.sh` 统一改为 `${VAR}`（入口脚本的权重缺失分支此前会直接崩，而不是给出提示）

### 新增
- **国内 torch CPU 轮子来源**：`TORCH_INDEX_URL=https://mirror.sjtu.edu.cn/pytorch-wheels/cpu/`
  （实测官方索引的索引页可达、但轮子主机 `download-r2.pytorch.org` 国内不可达 → 构建报
  `No matching distribution found for torch`；SJTU 镜像是标准 PEP 503 索引且含 `torch-2.9.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl`）
- Dockerfile 全面参数化：**基础镜像、镜像内路径（`APP_DIR`/`MODELS_DIR`）、运行用户（用户/UID/GID）、
  监听地址与端口、引擎/模型/后端、队列与超时、体积上限、鉴权（模式/密钥/头/公开路径/限流）** 全部可用
  `--build-arg` 赋值，并同步成运行期 `ENV`（运行期 `-e` 可再覆盖）；`scripts/docker-build.sh` 自动透传这些变量
- 入口脚本支持"不给命令就按环境变量起服务"：`LAYA_API_HOST` / `LAYA_API_PORT` / `LAYA_WORKERS`
  （端口从写死改为可赋值）；`ENTRYPOINT` 改为固定路径的符号链接，`APP_DIR` 改路径也不会失效
- `.env.docker.example` 补全为完整运行期变量清单

### 变更
- **权重默认打进镜像**（单文件交付）：`COPY weights/ /models/`，`docker load` 后直接 `docker run` 即可，无需挂载；
  想去掉 644MB 就让 `weights/` 只留 `.gitkeep`，用 `LAYA_MOUNT_MODELS=1` 走挂载。同时**移除 `VOLUME ["/models"]`**
  —— 声明 VOLUME 会在运行时生成匿名卷遮蔽镜像内权重，正是"权重进镜像"最容易踩的坑
- 容器内 `apt` 源可换（`DEBIAN_MIRROR`，`docker-build.sh` 默认清华源）：实测某些网络下 `deb.debian.org`
  被中间设备干扰，报 `Clearsigned file isn't valid, got 'NOSPLIT'`，apt 与 curl 都装不上
- pip 全部加 `--retries 10 --timeout 60`；新增 `PIP_FLAGS`（跨架构构建时传 `--no-compile` 提速）
- 镜像架构显式可控：`PLATFORM=linux/amd64 bash scripts/docker-build.sh <tag>`（跨架构构建走 buildx + `--load`），构建后自动核对产物架构并对 x86/arm 不匹配给出警告
- `requirements-docker.txt` 去掉不再需要的 `markdown`（`/wiki` 已改为纯 OpenAPI 渲染），并写明各依赖的架构支持与体积构成
- Dockerfile 构建期自检打印真实架构与 torch/laya 版本

## [1.0.0] - 2026-09-24

首个版本。

### 新增
- 版本化契约 `contract/decision.v1.schema.json` + 可直接回放的请求/响应样例
- HTTP 服务：`POST /v1/decide`、`GET /healthz`、`GET /readyz`、`GET /v1/status`、`GET /v1/presets`、`POST /v1/admin/reload`
- 三种问法语义层：`choice`（多选一）/ `score`（有序程度）/ `noul`（是否），客户端封装为 `choose` / `rate` / `yes_no`
- 多后端适配：`laya_mlx`（Apple Silicon，默认）/ `hermes_laya` / `laya_torch`（Linux 容器），由 `LAYA_ENGINE` 选择
- 内置离线文档：`/wiki`（OpenAPI 渲染）、`/docs`（Swagger UI）、`/redoc`，静态资源随包分发（不依赖 CDN）
- 内置测试台 `/ui`：零构建、离线可用
- 鉴权与限流（环境变量控制）：多密钥、`hmac.compare_digest` 比较、按密钥令牌桶、`429` + `Retry-After`
- 请求级 `policy` 与服务级环境变量两级控制，`/v1/status` 回显生效配置（不含密钥）
- 跨语言 SDK：Python（`src/laya_api/client.py`）、Java（`sdk/java/`，零依赖）、TypeScript（`sdk/ts/`，零依赖）
- 容器交付：独立单镜像（两级构建、非 root、HEALTHCHECK、基础镜像可换、权重只读挂载）
- 测试：`tests/run_contract_tests.py`（契约 + 语义 + HTTP + 鉴权 + 离线文档守门）

### 说明
- 稳定性与延迟均为 M4 / MLX / multilingual 实测值，见 README「运维与安全」与「工程约束」。
- 容器内使用 torch 后端；MLX 是 macOS + Metal 专属。
