# 第三方组件与许可

本仓库自身以 **Apache License 2.0** 发布（见 [LICENSE](LICENSE)）。
下表是随仓库/镜像分发的第三方组件。**分发构建产物时请一并保留许可原文。**

## 随包分发（必须保留许可）

| 组件 | 版本 | 许可 | 许可原文位置 | 用途 |
|---|---|---|---|---|
| swagger-ui-dist | 5.29.5 | Apache-2.0 | `src/laya_api/static/swagger/LICENSE.swagger-ui-dist` | `/docs` 页面（离线托管） |
| redoc | 2.5.1 | MIT | `src/laya_api/static/swagger/LICENSE.redoc` | `/redoc` 页面（离线托管） |

> 这两个前端资源是为了让文档页**离线可用**才随包内置（默认的 `/docs` 走 CDN，内网会白屏）。
> 我们没有改动它们，仅原样分发 + 在本仓库内引用。

## 运行期依赖（通过包管理器安装，不进本仓库）

| 依赖 | 许可 | 说明 |
|---|---|---|
| FastAPI | MIT | HTTP 框架 |
| Uvicorn | BSD-3-Clause | ASGI 服务器 |
| Pydantic | MIT | 契约模型（OpenAPI 真源） |
| HTTPX | BSD-3-Clause | 客户端与测试 |
| MLX（Apple） | MIT | Apple Silicon 推理后端 |
| PyTorch | BSD-3-Clause | Linux 容器推理后端 |
| Laya 决策模型 / laja-mlx / hermes-laya | 以上游声明为准 | **模型权重不随本仓库分发**；下游再分发前请自行确认上游许可 |

镜像构建与 Python 依赖安装会引入上述组件的各自许可与版权声明；对外交付镜像时，
请保留镜像内的 `dist-info/*/LICENSE`（pip 自动安装保留）与本文件。
