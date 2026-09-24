# 更新日志

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。契约变更请看 `contract/` 的版本后缀。

## [Unreleased]

### 新增
- `scripts/docker-ship.sh`：一条命令打包离线交付物（环境自检 → 构建 → 镜像内 import 自检 → `docker save` + SHA-256 → 打印服务器侧命令），支持 `WITH_WEIGHTS=1` 连权重一起打

### 修复
- 容器脚本里 `$VAR` 紧跟中文被 bash 当成变量名的一部分（`set -u` 下报 unbound variable）：`docker-build.sh` / `docker-entrypoint.sh` 统一改为 `${VAR}`（入口脚本的权重缺失分支此前会直接崩，而不是给出提示）

### 变更
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
