"""客户端：HTTP 薄客户端 + 阈值路由（网关模式）+ 进程内直调。

- LayaClient：跨语言/跨进程调用，只依赖契约。
- ThresholdRouter：低置信度回退（默认不介入，只有显式配置阈值才生效）。
- InProcessEngine：Hermes 工具 / context engine 直接复用同一引擎，省一跳 HTTP。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import httpx

from .engine import Engine
from .models import DecideRequest, DecideResponse

DEFAULT_BASE_URL = "http://127.0.0.1:8765"


class LayaError(RuntimeError):
    def __init__(self, code: str, message: str, details: Optional[dict] = None, status: Optional[int] = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.details, self.status = code, message, details, status


class _Answer(dict):
    """对调用方友好的结论对象：既能当 dict 用，也能点属性取。"""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(name) from exc

    def __repr__(self) -> str:  # 便于日志/REPL
        return f"<Answer {dict(self)}>"


def _confidence(a: dict) -> float:
    return float(a.get("confidence") or 0.0)


class SemanticsMixin:
    """语义层：把契约的 `questions/answers` 翻译成三种业务提问方式。

    只解决"怎么问、怎么读"，不改变契约——下面是同一份 HTTP 请求的三种语法糖：

    - ``choose``  选择类：这是哪一类 / 该分给谁
    - ``rate``    程度类：多严重 / 打几分
    - ``yes_no``  是非类：要不要 / 是不是
    """

    TAU_DEFAULT = 0.6   # 低于它就建议人工/大模型复核；业务阈值请用自己样本标定

    def _one(self, state, qid: str, definition: Dict[str, Any], tau: float, **policy: Any) -> Dict[str, Any]:
        resp = self.decide(state, questions={qid: definition}, **policy)  # type: ignore[attr-defined]
        return {"answer": resp.answers.get(qid, {}), "usage": resp.usage, "engine": resp.engine}

    @staticmethod
    def _gate(conf: float, tau: float, forced: Optional[bool] = None) -> Dict[str, Any]:
        auto = conf >= tau if forced is None else bool(forced)
        return {"confidence": round(conf, 4), "threshold": tau,
                "auto": auto, "needs_review": not auto,
                "hint": "可直接自动处理" if auto else "把握不足，建议转人工/大模型复核"}

    def choose(self, state: Any, question: str, options: Any, *, qid: str = "choice",
               instructions: Optional[str] = None, tau: float = TAU_DEFAULT, **policy: Any) -> _Answer:
        """选择类：在 options 里选一个。

        options：``["billing","technical"]`` 或 ``{"billing":"退款/计费","technical":"故障"}``
        返回：``label``（选中项）、``distribution``（各项概率，和为 1）、``confidence``、``auto``
        """
        payload = self._one(state, qid, {"type": "choice", "instructions": instructions or question,
                                         "criteria": options}, tau, **policy)
        a = payload["answer"]
        labels = list(options.keys()) if isinstance(options, dict) else list(options)
        dist = a.get("probabilities") or {}
        best = a.get("choice") or (max(dist, key=dist.get) if dist else None)
        return _Answer(question=qid, kind="choice", label=best,
                       distribution={k: dist.get(k) for k in labels} if labels else dist,
                       raw=a, usage=payload["usage"], engine=payload["engine"],
                       **self._gate(_confidence(a), tau))

    def rate(self, state: Any, question: str, levels: Any, *, qid: str = "rating",
             instructions: Optional[str] = None, tau: float = TAU_DEFAULT, **policy: Any) -> _Answer:
        """程度类：按从低到高的档位打分（levels 顺序即 0,1,2…）。

        返回：``score``（期望分，可为小数）、``level``（最接近的档位名）、``distribution``（各档位概率）
        """
        levels = list(levels)
        payload = self._one(state, qid, {"type": "score", "instructions": instructions or question,
                                         "criteria": levels}, tau, **policy)
        a = payload["answer"]
        dist = a.get("probabilities") or {}
        score = float(a.get("score") or 0.0)
        idx = max(0, min(len(levels) - 1, int(round(score))))
        return _Answer(question=qid, kind="score", score=round(score, 4), level=levels[idx] if levels else None,
                       scale=len(levels) - 1 if levels else None,
                       distribution={levels[int(k)]: v for k, v in dist.items() if str(k).isdigit()}
                       if levels else dist,
                       raw=a, usage=payload["usage"], engine=payload["engine"],
                       **self._gate(_confidence(a), tau))

    def yes_no(self, state: Any, question: str, *, qid: str = "yes_no",
               instructions: Optional[str] = None, yes_label: str = "yes", no_label: str = "no",
               tau: float = TAU_DEFAULT, **policy: Any) -> _Answer:
        """是非类：返回布尔判断 + 概率。

        返回：``answer``（True/False）、``probability``（P(True)）、``confidence``、``auto``
        """
        payload = self._one(state, qid, {"type": "noul", "instructions": instructions or question},
                            tau, **policy)
        a = payload["answer"]
        p = float(a.get("noul") or 0.0)
        return _Answer(question=qid, kind="yes_no", answer=p >= 0.5, probability=round(p, 4),
                       label=yes_label if p >= 0.5 else no_label, raw=a,
                       usage=payload["usage"], engine=payload["engine"],
                       **self._gate(_confidence(a), tau))


class LayaClient(SemanticsMixin):
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0,
                 api_key: Optional[str] = None, api_key_header: str = "X-API-Key"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        headers = {api_key_header: api_key} if api_key else None
        self._c = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "LayaClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- 读端点
    def healthz(self) -> dict:
        return self._c.get("/healthz").json()

    def readyz(self, warm: bool = False) -> dict:
        return self._c.get("/readyz", params={"warm": 1 if warm else 0}).json()

    def status(self) -> dict:
        return self._c.get("/v1/status").json()

    def presets(self) -> List[str]:
        return list(self._c.get("/v1/presets").json().get("presets", []))

    # ---- 写端点
    def decide(self, state: Any, questions: Optional[Dict[str, Any]] = None, preset: Optional[str] = None,
               request_id: Optional[str] = None, **policy: Any) -> DecideResponse:
        payload: Dict[str, Any] = {"state": state}
        if request_id:
            payload["request_id"] = request_id
        if questions is not None:
            payload["questions"] = questions
        if preset is not None:
            payload["preset"] = preset
        if policy:
            payload["policy"] = policy
        r = self._c.post("/v1/decide", json=payload)
        data = r.json()
        if r.status_code >= 400:
            err = data.get("error", {})
            raise LayaError(err.get("code", "INTERNAL"), err.get("message", r.text),
                            err.get("details"), r.status_code)
        return DecideResponse(**data)


class ThresholdRouter:
    """网关模式：laya 先判 → 置信度低于阈值就交回 LLM/规则（默认无回退则原样返回）。"""

    def __init__(self, thresholds: Optional[Dict[str, float]] = None, default: float = 0.6,
                 fallback: Optional[Callable[[Any, Dict[str, Any]], Any]] = None):
        self.thresholds = thresholds or {}
        self.default = default
        self.fallback = fallback

    def threshold_for(self, qid: str) -> float:
        return float(self.thresholds.get(qid, self.default))

    def route(self, state: Any, questions: Dict[str, Any], response: DecideResponse) -> Dict[str, Any]:
        accepted: Dict[str, Any] = {}
        review: List[Dict[str, Any]] = []
        for qid, ans in (response.answers or {}).items():
            conf = float(ans.get("confidence") or 0.0)
            if conf >= self.threshold_for(qid):
                accepted[qid] = ans
            else:
                review.append({"question": qid, "confidence": conf, "threshold": self.threshold_for(qid),
                               "answer": ans})
        out: Dict[str, Any] = {"route": "laya" if not review else ("fallback" if self.fallback else "laya"),
                               "accepted": accepted, "needs_review": review,
                               "usage": response.usage.model_dump()}
        if review and self.fallback is not None:
            out["fallback_result"] = self.fallback(state, {k: questions[k] for k in
                                                           (q["question"] for q in review) if k in questions})
        return out


class InProcessEngine(SemanticsMixin):
    """进程内直调（Hermes 工具 / context engine）。与 HTTP 服务共用 Engine 语义。"""

    def __init__(self, **kw: Any):
        self._engine = Engine(**kw)

    def warm(self, **kw: Any) -> dict:
        return self._engine.warm(**kw)

    def decide(self, state: Any, questions: Optional[Dict[str, Any]] = None, preset: Optional[str] = None,
               state_format: str = "auto", request_id: Optional[str] = None,
               policy: Optional[Dict[str, Any]] = None, **policy_kw: Any) -> DecideResponse:
        """原始契约入口（questions/answers 原样）。业务侧优先用 choose/rate/yes_no。"""
        """policy 可用 policy={...} 或关键字（timeout_ms=... 等）两种写法；state_format 与 HTTP 侧语义一致。"""
        merged: Dict[str, Any] = dict(policy or {})
        merged.update(policy_kw)
        req = DecideRequest(state=state, questions=questions, preset=preset,
                            state_format=state_format, request_id=request_id, policy=merged)
        return self._engine.decide(req)

    def status(self) -> dict:
        return self._engine.status()