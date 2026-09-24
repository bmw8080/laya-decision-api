"""引擎层：契约校验 → 决策后端（可插拔）→ 串行队列 → 类型化响应。

两种后端模式（LAYA_ENGINE 环境变量）：
- ``laya_mlx``   （默认）直连上游 ``laya_mlx`` 包，**完全不依赖 Hermes**，权重走本地目录。
- ``hermes_laya`` 走 Hermes 插件包 ``hermes_laya``（与 Hermes 工具/context engine 同一条代码路径）。

设计约束（来自实测）：
- MLX 单设备：推理串行，worker 单线程 + 有界队列，队列满回 BUSY。
- 单例缓存：每个 (模式, 后端, 模型) 只加载一次（实测 0.68–2.15s，常驻约 0.7GB fp16）。
- 序列预算：模型 512 token，选项过多会抛 ValueError → 接口层提前判 OVER_BUDGET。
"""
from __future__ import annotations

import importlib.metadata as md
import json
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import settings
from .models import ApiError, DecideRequest, DecideResponse, EngineInfo, Policy, Usage

DEFAULT_MODEL = "multilingual"
DEFAULT_ENGINE = os.getenv("LAYA_ENGINE", "laya_mlx").strip().lower()
ENGINE_MODES = ("laya_mlx", "laya_torch", "hermes_laya")
PRESET_NAMES = ("router", "guard", "moderation", "triage", "email")
PKG_NAMES = ("laya-mlx", "laya", "mlx", "hermes-laya")

# 上游权重坐标（与 laya_mlx.DEFAULT_MODELS 一致）：CPU/CUDA 容器里用 torch 后端按 (repo, subfolder) 加载
UPSTREAM_MODELS = {
    "english": ("convaiinnovations/laya", None),
    "multilingual": ("convaiinnovations/laya", "multilingual"),
    "typed-decisions": ("convaiinnovations/laya", "typed-decisions"),
}
TORCH_MODULE_HINTS = {
    "laya_torch": "pip install laya  # PyTorch 后端（Linux 容器用；CPU 或 CUDA）",
    "laya_mlx": "pip install laya-mlx  # Apple Silicon, macOS 14+",
    "hermes_laya": "pip install 'hermes-laya[mlx]'",
}


def pkg_versions(engine_mode: str = DEFAULT_ENGINE) -> str:
    parts: List[str] = [f"engine={engine_mode}"]
    for name in PKG_NAMES:
        if name == "hermes-laya" and engine_mode != "hermes_laya":
            continue
        try:
            parts.append(f"{name} {md.version(name)}")
        except Exception:
            pass
    return " / ".join(parts)


def local_model_dir(alias: str) -> str:
    """本地权重目录：LAYA_MODEL_DIR 优先，否则 ~/.cache/laya-models/<alias>。"""
    override = os.getenv("LAYA_MODEL_DIR")
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser(os.path.join("~/.cache/laya-models", alias))


# ---------------------------------------------------------------- 契约校验


def _validate_question(qid: str, q: Any, max_options: int) -> None:
    kind = q.type
    crit = q.criteria
    if kind == "choice":
        if isinstance(crit, list):
            if not crit:
                raise ApiError("SCHEMA_INVALID", f"question {qid!r}: choice 需要非空 criteria")
            if not all(isinstance(c, str) for c in crit):
                raise ApiError("SCHEMA_INVALID", f"question {qid!r}: choice 标签必须是字符串")
            if len(set(crit)) != len(crit):
                raise ApiError("SCHEMA_INVALID", f"question {qid!r}: choice 标签必须唯一")
            n = len(crit)
        elif isinstance(crit, dict):
            if not crit:
                raise ApiError("SCHEMA_INVALID", f"question {qid!r}: choice criteria 不能为空")
            if not all(isinstance(k, str) for k in crit):
                raise ApiError("SCHEMA_INVALID", f"question {qid!r}: choice 标签必须是字符串")
            n = len(crit)
        else:
            raise ApiError("SCHEMA_INVALID",
                           f"question {qid!r}: choice criteria 必须是 list[str] 或 {{label: 描述}}")
    elif kind == "score":
        if not isinstance(crit, list) or not crit:
            raise ApiError("SCHEMA_INVALID", f"question {qid!r}: score criteria 必须是非空 list[str]（等距档位）")
        n = len(crit)
    else:  # noul
        if crit is not None and not isinstance(crit, dict):
            raise ApiError("SCHEMA_INVALID", f"question {qid!r}: noul criteria 必须是 {{true: 描述, false: 描述}} 或省略")
        n = 2
    if n > max_options:
        raise ApiError("OVER_BUDGET",
                       f"question {qid!r}: 选项数 {n} 超过上限 {max_options}（模型 token 预算）",
                       {"options": n, "max_options": max_options})


def _prepare_state(state: Any, state_format: str, policy: Policy) -> Tuple[Any, List[str]]:
    warnings: List[str] = []
    if state is None:
        raise ApiError("SCHEMA_INVALID", "state 必填")
    if state_format == "text" and not isinstance(state, str):
        state = json.dumps(state, ensure_ascii=False)
    elif state_format == "json" and not isinstance(state, (dict, list)):
        raise ApiError("SCHEMA_INVALID", "state_format=json 时 state 必须是对象或数组")
    elif state_format == "messages" and not (isinstance(state, list) and all(isinstance(m, dict) for m in state)):
        raise ApiError("SCHEMA_INVALID", "state_format=messages 时 state 必须是 [{role, content}, ...]")
    text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
    if len(text) > policy.max_state_chars:
        if not policy.truncate_state:
            raise ApiError("OVER_BUDGET", f"state 长度 {len(text)} 超过 max_state_chars={policy.max_state_chars}",
                           {"chars": len(text), "max_state_chars": policy.max_state_chars})
        state = text[: policy.max_state_chars]
        warnings.append("state_truncated")
    return state, warnings


# ---------------------------------------------------------------- 后端加载


class _Job:
    __slots__ = ("state", "questions", "model", "backend", "policy", "event", "result", "error",
                 "queue_wait_ms", "cold_start", "enqueued_at")

    def __init__(self, state, questions, model, backend, policy):
        self.enqueued_at = 0.0
        self.state, self.questions = state, questions
        self.model, self.backend, self.policy = model, backend, policy
        self.event = threading.Event()
        self.result: Optional[DecideResponse] = None
        self.error: Optional[BaseException] = None
        self.queue_wait_ms = 0.0
        self.cold_start = False


class BackendAdapter:
    """决策后端适配：laya_mlx（独立）或 hermes_laya（与 Hermes 同源）。"""

    def __init__(self, mode: str = DEFAULT_ENGINE):
        mode = (mode or "laya_mlx").strip().lower()
        if mode not in ENGINE_MODES:
            raise ApiError("MODEL_UNAVAILABLE", f"未知 LAYA_ENGINE={mode!r}；可选 {', '.join(ENGINE_MODES)}")
        self.mode = mode

    # ---- 公共 API
    def load(self, alias: str, backend: Optional[str] = None) -> Tuple[Any, str, str]:
        alias = (alias or DEFAULT_MODEL).strip().lower()
        if self.mode == "laya_mlx":
            return self._load_laya_mlx(alias)
        if self.mode == "laya_torch":
            return self._load_laya_torch(alias)
        return self._load_hermes_laya(alias, backend)

    def preset(self, name: str, backend: Optional[str] = None) -> Dict[str, Any]:
        name = (name or "").strip().lower()
        if name not in PRESET_NAMES:
            raise ApiError("SCHEMA_INVALID", f"未知 preset {name!r}；可选 {', '.join(PRESET_NAMES)}")
        try:
            if self.mode == "laya_torch":
                import laya as mod
            if self.mode in ("laya_mlx", "laya_torch"):
                mod = __import__("laya" if self.mode == "laya_torch" else "laya_mlx")
                fn = getattr(mod, f"{name}_questions", None)
                if fn is None:
                    raise ApiError("SCHEMA_INVALID", f"后端未提供 {name}_questions()")
                return fn()
            from hermes_laya import backend as be
            return be.get_preset(name, backend=self._resolve_backend(backend, be))
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError("SCHEMA_INVALID", f"读取 preset {name!r} 失败：{exc}") from exc

    @staticmethod
    def _resolve_backend(be: Optional[str], be_mod: Any) -> str:
        """hermes_laya 的 get_agent 只认 mlx/coreml/torch；'auto' 需先探测。"""
        name = (be or "auto").strip().lower()
        return be_mod.detect_backend() if name == "auto" else name

    # ---- 具体实现
    def _load_laya_mlx(self, alias: str) -> Tuple[Any, str, str]:
        try:
            import laya_mlx
        except Exception as exc:  # 独立运行只需 laya-mlx + mlx
            raise ApiError("MODEL_UNAVAILABLE",
                           f"laya_mlx 不可用：{exc}",
                           {"hint": "pip install --index-url https://pypi.org/simple laya-mlx mlx"}) from exc
        path = local_model_dir(alias)
        if not os.path.isdir(path):
            raise ApiError("MODEL_UNAVAILABLE", f"本地权重目录不存在：{path}",
                           {"hint": "按 laya-local-deployment skill 用 ModelScope 下载权重到该目录"})
        return laya_mlx.load(path, cache_prompts=settings.get().prefix_cache), "mlx", alias

    def _load_laya_torch(self, alias: str) -> Tuple[Any, str, str]:
        """PyTorch 后端（Linux 容器/无 Metal 环境）。权重优先用本地目录，其次用上游 repo+subfolder。"""
        try:
            import laya  # pip install laya（PyTorch）
        except Exception as exc:
            raise ApiError("MODEL_UNAVAILABLE", f"torch 后端 laya 包不可用：{exc}",
                           {"hint": TORCH_MODULE_HINTS["laya_torch"]}) from exc
        os.environ.setdefault("USE_TF", "0")  # 上游注释：装了 TensorFlow 时 import 会死锁
        local = local_model_dir(alias)
        try:
            if os.path.isdir(local):
                return laya.load(local), "torch", alias
            repo, subfolder = UPSTREAM_MODELS.get(alias, (None, None))
            if not repo:
                raise ApiError("MODEL_UNAVAILABLE", f"未知模型别名 {alias!r}；本地目录也不存在 {local}")
            agent = laya.load(repo, subfolder=subfolder) if subfolder else laya.load(repo)
            return agent, "torch", alias
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError("MODEL_UNAVAILABLE", f"torch 后端加载失败：{exc}",
                           {"model_dir": local, "repo": UPSTREAM_MODELS.get(alias)}) from exc

    def _load_hermes_laya(self, alias: str, backend: Optional[str]) -> Tuple[Any, str, str]:
        try:
            from hermes_laya import backend as be
        except Exception as exc:
            raise ApiError("MODEL_UNAVAILABLE",
                           f"hermes_laya 不可用：{exc}。跑 bash scripts/ensure-laya-install.sh",
                           {"hint": "pip install --index-url https://pypi.org/simple 'hermes-laya[mlx]'"}) from exc
        resolved = self._resolve_backend(backend, be)
        try:
            return be.get_agent(model=alias, backend=resolved)
        except Exception as exc:
            raise ApiError("MODEL_UNAVAILABLE", f"加载失败：{exc}") from exc


class Engine:
    """进程内唯一入口：HTTP 服务与进程内直调都走它。"""

    def __init__(self, model: str = DEFAULT_MODEL, backend: str = "auto", max_queue: int = 16,
                 engine_mode: Optional[str] = None):
        self.model = model
        self.backend = backend
        self.engine_mode = (engine_mode or DEFAULT_ENGINE).strip().lower()
        self._adapter = BackendAdapter(self.engine_mode)
        self._resolved_backend: Optional[str] = None
        self._loaded_keys: Dict[Tuple[str, str], str] = {}
        self._load_ms: Dict[Tuple[str, str], float] = {}
        self._queue: "queue.Queue[_Job]" = queue.Queue(maxsize=max_queue)
        self._worker = threading.Thread(target=self._loop, name="laya-worker", daemon=True)
        self._worker.start()
        self._stats = {"requests": 0, "errors": 0, "timeouts": 0, "busy": 0, "latencies": []}
        self._stats_lock = threading.Lock()

    # ------------------------------------------------------------ 加载

    def warm(self, model: Optional[str] = None, backend: Optional[str] = None) -> Dict[str, Any]:
        """加载（或命中缓存）模型；返回加载信息。幂等。"""
        alias = (model or self.model).strip().lower()
        key = (self.engine_mode, alias)
        t0 = time.perf_counter()
        agent, resolved_backend, resolved_alias = self._adapter.load(alias, backend or self.backend)
        self._resolved_backend = resolved_backend
        ms = round((time.perf_counter() - t0) * 1000.0, 2)
        cold = key not in self._loaded_keys
        self._loaded_keys[key] = type(agent).__name__
        self._load_ms.setdefault(key, ms)
        return {"model": resolved_alias, "backend": resolved_backend, "engine_mode": self.engine_mode,
                "load_ms": ms, "cold_start": cold, "loaded": self.loaded_agents()}

    def loaded_agents(self) -> List[str]:
        return sorted(f"{m}/{k}" for (m, k) in self._loaded_keys)

    def is_ready(self) -> bool:
        return bool(self._loaded_keys)

    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------ 执行

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            job.queue_wait_ms = round((time.perf_counter() - job.enqueued_at) * 1000.0, 2)
            try:
                job.result = self._infer(job)
            except BaseException as exc:  # noqa: BLE001 - 交给调用线程转成错误码
                job.error = exc
            finally:
                job.event.set()
                self._queue.task_done()

    def _infer(self, job: _Job) -> DecideResponse:
        t0 = time.perf_counter()
        agent, resolved_backend, alias = self._adapter.load(job.model, job.backend)
        self._resolved_backend = resolved_backend
        cold = (self.engine_mode, (job.model or self.model).lower()) not in self._loaded_keys
        load_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        self._loaded_keys[(self.engine_mode, alias)] = type(agent).__name__
        self._load_ms.setdefault((self.engine_mode, alias), load_ms)

        t1 = time.perf_counter()
        try:
            result = agent.predict(job.state, job.questions)
        except ValueError as exc:
            msg = str(exc)
            code = "OVER_BUDGET" if "too many options" in msg or "token budget" in msg else "SCHEMA_INVALID"
            raise ApiError(code, msg) from exc
        except FloatingPointError as exc:
            raise ApiError("INTERNAL", f"模型输出非有限值：{exc}", {"hint": "dtype=float32 重试"}) from exc
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError("MODEL_UNAVAILABLE", f"推理失败：{exc}", {"hint": "检查 mlx 权重与内存"}) from exc
        latency_ms = round((time.perf_counter() - t1) * 1000.0, 2)

        if not isinstance(result, dict):
            result = {"answers": result}
        answers = result.get("answers", result)
        usage_raw = result.get("usage") or {}
        job.cold_start = cold
        with self._stats_lock:
            self._stats["requests"] += 1
            self._stats["latencies"].append(latency_ms)
            if len(self._stats["latencies"]) > 500:
                self._stats["latencies"] = self._stats["latencies"][-500:]
        return DecideResponse(
            request_id=None,
            engine=EngineInfo(model=alias, backend=resolved_backend,
                              pkg=pkg_versions(self.engine_mode), engine_mode=self.engine_mode),
            answers=answers,
            usage=Usage(latency_ms=latency_ms, queue_wait_ms=job.queue_wait_ms,
                        input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
                        output_tokens=int(usage_raw.get("output_tokens", 0) or 0),
                        cold_start=cold),
            warnings=[],
        )

    def decide(self, req: DecideRequest) -> DecideResponse:
        cfg = settings.get()
        policy = req.policy or Policy()
        # 0 = 未指定 → 用服务端默认（环境变量可统一调）
        if not policy.timeout_ms:
            policy.timeout_ms = cfg.default_timeout_ms
        if not policy.max_state_chars:
            policy.max_state_chars = cfg.max_state_chars
        if not policy.max_options:
            policy.max_options = cfg.max_options
        if (req.questions is None) == (req.preset is None):
            raise ApiError("SCHEMA_INVALID", "questions 与 preset 必须二选一")
        if req.questions is not None:
            questions: Dict[str, Any] = {qid: q.model_dump(exclude_none=True) for qid, q in req.questions.items()}
            for qid, q in req.questions.items():
                _validate_question(qid, q, policy.max_options)
        else:
            questions = self._adapter.preset(req.preset or "", policy.backend)

        state, warnings = _prepare_state(req.state, req.state_format, policy)
        job = _Job(state, questions, policy.model or self.model, policy.backend or self.backend, policy)
        enq = time.perf_counter()
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            with self._stats_lock:
                self._stats["busy"] += 1
            raise ApiError("BUSY", f"队列已满（max_queue={self._queue.maxsize}）")
        job.enqueued_at = enq
        if not job.event.wait(policy.timeout_ms / 1000.0):
            with self._stats_lock:
                self._stats["timeouts"] += 1
            raise ApiError("TIMEOUT", f"超过 timeout_ms={policy.timeout_ms}",
                           {"inference_still_running": True,
                            "note": "MLX 推理不可中断；本次前向跑完才会释放 worker"})
        if job.error is not None:
            with self._stats_lock:
                self._stats["errors"] += 1
            if isinstance(job.error, ApiError):
                raise job.error
            raise ApiError("INTERNAL", f"{type(job.error).__name__}: {job.error}")
        assert job.result is not None
        job.result.request_id = req.request_id
        job.result.warnings = list(warnings)
        return job.result

    # ------------------------------------------------------------ 观测

    def status(self) -> Dict[str, Any]:
        with self._stats_lock:
            lats = sorted(self._stats["latencies"])
            stats = {"requests": self._stats["requests"], "errors": self._stats["errors"],
                     "timeouts": self._stats["timeouts"], "busy": self._stats["busy"]}

        def pct(p: float) -> Optional[float]:
            if not lats:
                return None
            idx = min(len(lats) - 1, int(round((len(lats) - 1) * p)))
            return lats[idx]

        return {
            "engine": {"engine_mode": self.engine_mode, "model": self.model,
                       "backend": self._resolved_backend or self.backend, "backend_configured": self.backend,
                       "pkg": pkg_versions(self.engine_mode), "loaded": self.loaded_agents(),
                       "model_dir": local_model_dir(self.model) if self.engine_mode == "laya_mlx" else None,
                       "load_ms": {f"{m}/{k}": v for (m, k), v in self._load_ms.items()}},
            "queue": {"depth": self.queue_depth(), "max": self._queue.maxsize, "concurrency": 1},
            "latency_ms": {"p50": pct(0.50), "p95": pct(0.95), "samples": len(lats)},
            "counters": stats,
        }
