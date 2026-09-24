"""FastAPI 服务：/v1/decide 等接口 + 内置测试台(/ui) + 内置文档(/wiki)。

范式说明（OpenAPI 优先）：
- 所有模型带 Field 描述与示例 → `/openapi.json` 就是权威接口描述（OpenAPI 3.1）
- 路由带 summary/description/responses（含各错误码的 ErrorResponse 形状）
- `/wiki` 页面**直接渲染 /openapi.json**（不再手写字段表）→ 文档与接口不可能漂移
- 唯一的例外是 `/ui`（测试台）：它是"Try it out"的本地替代，离线可用
"""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, settings
from .engine import DEFAULT_MODEL, Engine, pkg_versions
from .models import ApiError, DecideRequest, DecideResponse, ErrorBody, ErrorResponse

BOOT = settings.get()                     # 启动时的配置快照（运行期改 env 需 /v1/admin/reload 或重启）
WARM_ON_START = BOOT.warm_on_start

engine = Engine(model=BOOT.model or DEFAULT_MODEL, backend=BOOT.backend or "auto",
                max_queue=BOOT.max_queue, engine_mode=BOOT.engine_mode)


def authorize(request: Request) -> Optional[str]:
    """鉴权依赖：AuthSettings 关时不校验；开时校验密钥并按密钥限流。返回密钥指纹（无鉴权为 None）。"""
    return auth.guard.check(request.url.path, dict(request.headers))

# 所有错误码在 OpenAPI 里都指向同一个 ErrorResponse 信封
ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "SCHEMA_INVALID：字段类型/选项不合法"},
    413: {"model": ErrorResponse, "description": "OVER_BUDGET：情境或选项超 token 预算"},
    503: {"model": ErrorResponse, "description": "BUSY / MODEL_UNAVAILABLE：队列满或后端不可用"},
    504: {"model": ErrorResponse, "description": "TIMEOUT：超过 timeout_ms"},
}

TAGS_METADATA = [
    {"name": "decide", "description": "决策：给情境与问题，拿回结论与把握程度"},
    {"name": "ops", "description": "运维：健康检查、就绪、状态、内置问题集"},
    {"name": "docs", "description": "内置文档与测试台（离线可用，不依赖任何 CDN）"},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if WARM_ON_START:
        def _warm() -> None:
            try:
                engine.warm()
            except ApiError:
                pass  # /readyz 会如实报告；启动不因模型问题而失败

        threading.Thread(target=_warm, name="laya-warm", daemon=True).start()
    yield


def _pkg_version() -> str:
    """发布版本以 pyproject.toml 为唯一来源；取不到时回落到内置值。"""
    try:
        from importlib.metadata import version as _dist_version

        return _dist_version("laya-decision-api")
    except Exception:
        return "1.0.1"


app = FastAPI(
    title="Laya 决策服务",
    version=_pkg_version(),
    description=(
        "本地 System-1 决策模型的 HTTP 服务：交「情境 + 问题」，回「结论 + 把握程度」。\n\n"
        "三种问法 choice / score / noul；读结果只看两项 —— 结论与 confidence（≥τ 自动处理，<τ 转人工）。\n\n"
        "本页只做接口参考；开发者说明见仓库 README 与 docs/。"
    ),
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
    # 自带 /docs 与 /redoc 引用 CDN，离线会白屏；这里关掉，改用本地托管的静态资源（见下）
    docs_url=None,
    redoc_url=None,
)

# ── OpenAPI 版本：默认 3.1（FastAPI 原生）；LAYA_OPENAPI_VERSION=3.0 时对外降级为 3.0.3 ──
# 为什么要降级：不少企业 API 平台只认 3.0.x，读到 3.1 会报「无法读取 openapi 信息 / 版本不是 3.0.x」。
# 无论开关怎么设，专门的 /openapi-3.0.json 始终可用（固定 3.0.3，给平台导入用）。
_native_openapi = app.openapi


def _openapi_with_version() -> dict:
    doc = _native_openapi()
    cfg = settings.get()
    if str(cfg.openapi_version).startswith("3.0"):
        from .openapi30 import to_openapi_30
        return to_openapi_30(doc, server_url=cfg.openapi_server_url or None)
    return doc


app.openapi = _openapi_with_version


@app.get("/openapi-3.0.json", tags=["ops"], summary="OpenAPI 3.0.3 文档（给只认 3.0.x 的平台导入）",
         include_in_schema=False)
def openapi_30_json() -> JSONResponse:
    from .openapi30 import to_openapi_30
    cfg = settings.get()
    doc = to_openapi_30(_native_openapi(), server_url=cfg.openapi_server_url or None)
    return JSONResponse(content=doc, media_type="application/json")


@app.get("/openapi-kingdee.json", tags=["ops"],
         summary="OpenAPI 3.0.3 扁平化档（给金蝶苍穹等自研 schema 转换器用）",
         include_in_schema=False)
def openapi_kingdee_json() -> JSONResponse:
    """彻底摊平：内联全部 $ref、消掉 allOf/anyOf/oneOf、每个节点都带 type。

    苍穹的 JsonSchemaToParamDefinitionConverter 对 $ref/复合关键字会抛 NPE，这一档就是给它用的。
    """
    from .openapi30 import to_kingdee_profile
    cfg = settings.get()
    doc = to_kingdee_profile(_native_openapi(), server_url=cfg.openapi_server_url or None)
    return JSONResponse(content=doc, media_type="application/json")


# 本地托管的 swagger-ui / redoc 静态资源（随包发布：src/laya_api/static/swagger/）
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=exc.code, message=exc.message, details=exc.details))
    headers = {}
    if exc.code in {"BUSY", "RATE_LIMITED"}:
        retry = settings.get().busy_retry_after_s
        if exc.code == "RATE_LIMITED" and (exc.details or {}).get("retry_after_s"):
            retry = max(retry, int(float(exc.details["retry_after_s"]) + 0.999))
        headers["Retry-After"] = str(max(1, retry))
    return JSONResponse(status_code=exc.status, content=body.model_dump(), headers=headers)


@app.exception_handler(Exception)
async def _internal_handler(request: Request, exc: Exception) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code="INTERNAL", message=f"{type(exc).__name__}: {exc}"))
    return JSONResponse(status_code=500, content=body.model_dump())


# ---------------------------------------------------------------- docs / ui

# Swagger UI / ReDoc：用本地静态资源，离线可用（不引用任何 CDN）
_SWAGGER_PARAMS = {"docExpansion": "list", "defaultModelsExpandDepth": 2, "tryItOutEnabled": True}


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False, tags=["docs"])
def swagger_ui() -> HTMLResponse:
    """标准 Swagger UI（本地托管资源，离线可用，可 Try it out）。"""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} · Swagger UI",
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
        swagger_favicon_url="",
        swagger_ui_parameters=_SWAGGER_PARAMS,
    )


@app.get("/redoc", response_class=HTMLResponse, include_in_schema=False, tags=["docs"])
def redoc_ui() -> HTMLResponse:
    """标准 ReDoc（本地托管资源，离线可用）。"""
    return get_redoc_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} · ReDoc",
        redoc_js_url="/static/swagger/redoc.standalone.js",
        redoc_favicon_url="",
    )


@app.get("/wiki", response_class=HTMLResponse, include_in_schema=False, tags=["docs"])
@app.get("/docs/wiki", response_class=HTMLResponse, include_in_schema=False, tags=["docs"])
def wiki() -> HTMLResponse:
    """内置接口文档：渲染 /openapi.json（字段/必填/默认/示例全部来自实现）+ 语义说明全文。"""
    from .wiki import build_page
    return HTMLResponse(build_page(app.openapi()))


@app.get("/", response_class=HTMLResponse, include_in_schema=False, tags=["docs"])
@app.get("/ui", response_class=HTMLResponse, include_in_schema=False, tags=["docs"])
def ui() -> HTMLResponse:
    """本地测试台：单文件页面，无外链（离线可用），直接调同源接口。"""
    from .ui import PAGE
    return HTMLResponse(PAGE)


# ---------------------------------------------------------------- ops

@app.get("/healthz", tags=["ops"], summary="进程存活（不碰模型）",
         description="只要进程活着就 200；模型是否已加载看 `ready` 字段或 `/readyz`。")
def healthz() -> dict:
    return {"status": "ok", "ready": engine.is_ready(), "pkg": pkg_versions()}


@app.get("/readyz", tags=["ops"], summary="就绪检查（可选触发加载）")
def readyz(warm: int = Query(0, description="1 = 先加载模型再回答（首次约 1–3 秒）")) -> dict:
    if warm:
        info = engine.warm()
        return {"ready": True, **info}
    return {"ready": engine.is_ready(), "loaded": engine.loaded_agents()}


@app.get("/v1/status", tags=["ops"], summary="运行状态：引擎/队列/延迟分位/计数 + 生效配置",
         dependencies=[Depends(authorize)])
def status() -> dict:
    return engine.status() | {"config": settings.get().public()}


@app.post("/v1/admin/reload", tags=["ops"], summary="重新读取环境变量（密钥/限流等），无需重启进程",
          dependencies=[Depends(authorize)])
def reload_settings() -> dict:
    cfg = settings.reload_from_env()
    auth.guard.refresh()
    return {"reloaded": True, "config": cfg.public()}


@app.get("/v1/presets", tags=["ops"], summary="列出内置问题集名称")
def presets() -> dict:
    try:
        from hermes_laya import backend as laya_backend  # noqa: F401
        names = ["router", "guard", "moderation", "triage", "email"]
    except Exception:
        names = ["router", "guard", "moderation", "triage", "email"]
    return {"presets": names}


# ---------------------------------------------------------------- decide

@app.post("/v1/decide", response_model=DecideResponse, tags=["decide"],
          summary="一次决策：给情境与问题，返回结论与概率",
          description=(
              "`questions` 与 `preset` 二选一。一次前向可同时问多个问题（几乎不增加耗时）。\n\n"
              "返回的 `answers` 里：choice 给选中标签，score 给期望分+档位名，noul 给 P(是)；"
              "三者都带 `confidence` 与 `probabilities`。服务端**不替业务定阈值**。"
          ),
          responses=ERROR_RESPONSES)
def decide(req: DecideRequest, key_id: Optional[str] = Depends(authorize)) -> DecideResponse:
    resp = engine.decide(req)
    if key_id:
        resp.usage.model_extra  # 保留：调用方密钥指纹不落响应（只进服务端统计）
    return resp
