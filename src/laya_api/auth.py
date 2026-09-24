"""鉴权与限流：环境变量驱动，默认关闭（本机/内网可信场景）。

要点：
- 多密钥并存（`LAYA_API_KEYS=k1,k2`）便于轮换；比较用 `hmac.compare_digest`（防时序侧信道）
- **绝不记录密钥明文**：日志/状态里只出现指纹前 8 位
- 429 带 `Retry-After`；BUSY 同理（见 server 的异常处理）
- 健康检查/文档/测试台默认公开，只有业务接口（/v1/decide、可选 /v1/status）需要密钥
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import settings
from .models import ApiError


def fingerprint(key: str) -> str:
    """密钥指纹（仅用于日志/统计，不可逆推）。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def extract_key(headers: Dict[str, str], header_name: str) -> Optional[str]:
    raw = headers.get(header_name) or headers.get(header_name.lower())
    if not raw and header_name.lower() != "authorization":
        raw = headers.get("authorization") or headers.get("Authorization")
        if raw and raw.lower().startswith("bearer "):
            return raw[7:].strip()
    if raw and raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw.strip() if raw else None


class _Bucket:
    __slots__ = ("tokens", "updated", "capacity", "rate_per_s")

    def __init__(self, capacity: int, rate_per_s: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.rate_per_s = rate_per_s
        self.updated = time.monotonic()

    def take(self) -> Tuple[bool, float]:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate_per_s)
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0.0
        deficit = 1.0 - self.tokens
        return False, max(0.05, deficit / self.rate_per_s if self.rate_per_s else 60.0)


class AuthGuard:
    """按密钥做鉴权 + 令牌桶限流；AuthSettings 变更后调用 `refresh()` 生效。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, _Bucket] = {}
        self.refresh()

    def refresh(self) -> None:
        self.cfg = settings.get().auth
        with self._lock:
            self._buckets.clear()

    def is_public(self, path: str) -> bool:
        cfg = self.cfg
        if path.startswith("/v1/status"):
            return not cfg.protect_status          # 内网排障默认放开，可开关
        if path in cfg.public_paths:
            return True
        return any(path.startswith(p.rstrip("/") + "/") for p in cfg.public_paths if p not in ("/",))

    def check(self, path: str, headers: Dict[str, str]) -> Optional[str]:
        """通过则返回密钥指纹（无鉴权时返回 None）；不通过直接抛 ApiError。"""
        cfg = self.cfg
        if not cfg.enabled or self.is_public(path):
            return None
        key = extract_key(headers, cfg.header)
        if not key:
            raise ApiError("UNAUTHORIZED", f"缺少密钥：请在 {cfg.header} 头提供（或 Authorization: Bearer <key>）")
        matched = False
        for candidate in cfg.keys:
            if hmac.compare_digest(key, candidate):
                matched = True
                break
        if not matched:
            raise ApiError("UNAUTHORIZED", "密钥无效")
        fp = fingerprint(key)
        if cfg.rate_limit_per_min > 0:
            capacity = cfg.rate_limit_burst or cfg.rate_limit_per_min
            with self._lock:
                bucket = self._buckets.get(fp)
                if bucket is None:
                    bucket = _Bucket(capacity, cfg.rate_limit_per_min / 60.0)
                    self._buckets[fp] = bucket
            ok, retry_after = bucket.take()
            if not ok:
                raise ApiError("RATE_LIMITED", f"超出速率上限（{cfg.rate_limit_per_min}/分钟）",
                               {"retry_after_s": round(retry_after, 2)})
        return fp


guard = AuthGuard()
