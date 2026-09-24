"""统一配置：所有开关都是环境变量，集中在这里读一次，便于交接与运维核对。

命名约定：`LAYA_*`。密钥类只进环境/密钥文件，**绝不写进镜像或代码**。
`GET /v1/status` 会回显生效配置（密钥只显示数量，不显示值），便于现场自查。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off", ""}


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in TRUTHY:
        return True
    if v in FALSY:
        return False
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, "")).strip())
    except Exception:
        return default


def _csv(name: str, default: Optional[List[str]] = None) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default or [])
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass
class AuthSettings:
    """鉴权配置。

    mode=off      : 不校验（仅限本机/内网可信环境，默认）
    mode=api_key  : 校验调用方密钥，支持多把并存（便于轮换）
    """
    mode: str = "off"                       # off | api_key
    keys: List[str] = field(default_factory=list)
    header: str = "X-API-Key"               # 也接受 Authorization: Bearer <key>
    protect_status: bool = False            # /v1/status 是否也要密钥（内网排障默认放开）
    public_paths: List[str] = field(default_factory=lambda: [
        "/healthz", "/readyz", "/docs", "/redoc", "/wiki", "/docs/wiki", "/ui", "/", "/openapi.json", "/static",
    ])
    rate_limit_per_min: int = 0             # 0 = 不限流；>0 时按密钥限流
    rate_limit_burst: int = 0               # 0 = 等于 per_min

    @property
    def enabled(self) -> bool:
        return self.mode == "api_key" and bool(self.keys)

    def public(self) -> Dict[str, Any]:
        """可安全回显的部分（不含密钥值）。"""
        return {
            "mode": self.mode, "keys_configured": len(self.keys), "header": self.header,
            "protect_status": self.protect_status, "public_paths": self.public_paths,
            "rate_limit_per_min": self.rate_limit_per_min, "rate_limit_burst": self.rate_limit_burst,
        }


@dataclass
class Settings:
    # 形态
    engine_mode: str = "laya_mlx"
    model: str = "multilingual"
    backend: str = "auto"
    model_dir: str = ""
    prefix_cache: bool = True               # 缓存问题前缀，重复问题集更快（实测 ~6%）
    warm_on_start: bool = True

    # 文档（部分企业平台只认 OpenAPI 3.0.x；这里可切默认对外版本）
    openapi_version: str = "3.1"            # 3.1（FastAPI 原生）| 3.0（降级为 3.0.3，兼容老平台）
    openapi_server_url: str = ""            # 文档里的 servers[0].url，留空则用相对路径 "/"

    # 并发与超时
    max_queue: int = 16                     # 超过直接 BUSY，避免无限堆积
    default_timeout_ms: int = 5000          # 请求未指定时的默认超时
    busy_retry_after_s: int = 1             # BUSY/限流时给调用方的 Retry-After

    # 体积上限
    max_state_chars: int = 4000
    max_options: int = 20

    # 鉴权
    auth: AuthSettings = field(default_factory=AuthSettings)

    def public(self) -> Dict[str, Any]:
        d = asdict(self)
        d["auth"] = self.auth.public()
        return d


def load() -> Settings:
    return Settings(
        engine_mode=os.getenv("LAYA_ENGINE", "laya_mlx").strip().lower(),
        model=os.getenv("LAYA_MODEL", "multilingual").strip(),
        backend=os.getenv("LAYA_BACKEND", "auto").strip(),
        model_dir=os.getenv("LAYA_MODEL_DIR", "").strip(),
        prefix_cache=_flag("LAYA_PREFIX_CACHE", True),
        warm_on_start=_flag("LAYA_WARM_ON_START", True),
        openapi_version=os.getenv("LAYA_OPENAPI_VERSION", "3.1").strip() or "3.1",
        openapi_server_url=os.getenv("LAYA_OPENAPI_SERVER_URL", "").strip(),
        max_queue=_int("LAYA_MAX_QUEUE", 16),
        default_timeout_ms=_int("LAYA_DEFAULT_TIMEOUT_MS", 5000),
        busy_retry_after_s=_int("LAYA_BUSY_RETRY_AFTER_S", 1),
        max_state_chars=_int("LAYA_MAX_STATE_CHARS", 4000),
        max_options=_int("LAYA_MAX_OPTIONS", 20),
        auth=AuthSettings(
            mode=os.getenv("LAYA_AUTH_MODE", "off").strip().lower(),
            keys=_csv("LAYA_API_KEYS"),
            header=os.getenv("LAYA_AUTH_HEADER", "X-API-Key").strip() or "X-API-Key",
            protect_status=_flag("LAYA_AUTH_PROTECT_STATUS", False),
            public_paths=_csv("LAYA_AUTH_PUBLIC_PATHS", AuthSettings().public_paths),
            rate_limit_per_min=_int("LAYA_RATE_LIMIT_PER_MIN", 0),
            rate_limit_burst=_int("LAYA_RATE_LIMIT_BURST", 0),
        ),
    )


_settings: Settings = load()


def get() -> Settings:
    return _settings


def reload_from_env() -> Settings:
    """重新读取环境变量（测试与运行期改配置用，无需重启进程）。"""
    global _settings
    _settings = load()
    return _settings
