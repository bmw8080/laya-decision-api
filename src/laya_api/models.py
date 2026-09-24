"""v1 契约模型（pydantic v2）。

这些模型的 Field 描述会直接进 OpenAPI（/openapi.json），因此文档与实现同源：
改这里 = 改接口文档，不会出现"文档没跟上"。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "1"

ERROR_STATUS = {
    "SCHEMA_INVALID": 400,
    "UNAUTHORIZED": 401,
    "OVER_BUDGET": 413,
    "RATE_LIMITED": 429,
    "BUSY": 503,
    "MODEL_UNAVAILABLE": 503,
    "TIMEOUT": 504,
    "INTERNAL": 500,
}

_STATE_EXAMPLE = {"subject": "登录失败", "body": "系统登录失败，全组都无法使用"}
_QUESTIONS_EXAMPLE = {
    "department": {
        "type": "choice",
        "instructions": "该由哪个团队处理？",
        "criteria": {"billing": "退款/计费", "technical": "故障/缺陷"},
    },
    "needs_human": {"type": "noul", "instructions": "需要人工介入吗？"},
}


class ApiError(Exception):
    """带错误码的业务异常：服务端统一转成 ErrorResponse。"""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status = ERROR_STATUS.get(code, 500)


class Policy(BaseModel):
    """策略（可选）：只影响"怎么算"，不改变判断语义。"""

    model_config = ConfigDict(extra="allow")
    model: Optional[str] = Field(
        default=None,
        description="权重选择：multilingual（默认，中文/多语）/ english / typed-decisions",
        examples=["multilingual"],
    )
    backend: Optional[str] = Field(
        default=None, description="计算后端：auto（默认）/ mlx / coreml / torch", examples=["auto"]
    )
    timeout_ms: int = Field(default=0, description="超时毫秒；0 = 用服务默认（LAYA_DEFAULT_TIMEOUT_MS）", examples=[0])
    max_state_chars: int = Field(default=0, description="情境截断长度；0 = 用服务默认（LAYA_MAX_STATE_CHARS）")
    max_options: int = Field(default=0, description="单个问题的选项数上限；0 = 用服务默认（LAYA_MAX_OPTIONS）")
    max_queue: int = Field(default=0, description="保留字段（排队上限由服务端 LAYA_MAX_QUEUE 决定）")
    truncate_state: bool = Field(
        default=True, description="超长是截断（true，默认，回 warning state_truncated）还是报错 OVER_BUDGET（false）"
    )
    return_probabilities: bool = Field(default=True, description="是否返回 probabilities 概率分布（建议保持 true）")


class Question(BaseModel):
    """一个问题定义：问法 + 问什么 + 候选项。"""

    model_config = ConfigDict(extra="allow")
    type: Literal["choice", "score", "noul"] = Field(
        description="问法：choice 选择类（多选一）/ score 程度类（有序档位）/ noul 是非类（布尔）",
        examples=["choice"],
    )
    instructions: Any = Field(
        description="用自然语言写清要判断什么", examples=["该由哪个团队处理？"]
    )
    criteria: Optional[Any] = Field(
        default=None,
        description=(
            "候选项。choice：{\"标签\": \"说明\"} 或 [\"标签\"]（必填、标签唯一）；"
            "score：从低到高的档位数组（必填）；noul：可省"
        ),
        examples=[{"billing": "退款/计费", "technical": "故障/缺陷"}],
    )


class DecideRequest(BaseModel):
    """决策请求：给「情境 + 要判断的问题」，拿回「结论 + 把握程度」。"""

    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [{
        "api_version": "1",
        "state": _STATE_EXAMPLE,
        "questions": _QUESTIONS_EXAMPLE,
    }]})
    api_version: str = Field(default=API_VERSION, description='契约版本，固定 "1"', examples=["1"])
    request_id: Optional[str] = Field(
        default=None, description="调用方追踪号，原样回显（建议带上，便于日志对账）", examples=["order-20260924-001"]
    )
    state: Any = Field(
        description="情境：纯文本 / JSON 对象 / 消息数组（[{\"role\",\"content\"}]）",
        examples=[_STATE_EXAMPLE],
    )
    state_format: Literal["auto", "text", "json", "messages"] = Field(
        default="auto", description="情境格式；auto = 按原样交给模型序列化器"
    )
    questions: Optional[Dict[str, Question]] = Field(
        default=None, description="要判断的问题：{问题名: 问题定义}；与 preset 二选一（一次前向可给多个问题）"
    )
    preset: Optional[str] = Field(
        default=None,
        description="内置问题集：router（小模型 vs 大模型）/ guard（越狱注入）/ moderation（内容安全）/ triage（工单）；与 questions 二选一",
        examples=["triage"],
    )
    policy: Policy = Field(default_factory=Policy, description="策略；可省略，字段都有默认值")


class Usage(BaseModel):
    """本次调用的运行信息（不是计费口径：本地模型不产生 token 费用）。"""

    latency_ms: float = Field(default=0.0, description="纯推理耗时（毫秒）")
    queue_wait_ms: float = Field(default=0.0, description="排队耗时（单 worker 串行，毫秒）")
    input_tokens: int = Field(default=0, description="本次消耗的上下文长度（容量参考，不计费）")
    output_tokens: int = Field(default=0, description="恒为 0：模型不做生成")
    cold_start: bool = Field(default=False, description="是否走了冷启动（首次加载模型）")


class EngineInfo(BaseModel):
    """实际执行本次判断的形态与版本。"""

    model: str = Field(description="权重别名：multilingual / english / typed-decisions")
    backend: str = Field(description="实际计算后端：mlx（Mac）/ torch（容器）/ coreml")
    pkg: str = Field(default="", description="组件版本串（engine=… / laya-mlx … / mlx …）")
    engine_mode: str = Field(default="", description="引擎模式：laya_mlx / laya_torch / hermes_laya")


class DecideResponse(BaseModel):
    """决策响应：answers 里有结论与把握程度，usage 里有运行信息。"""

    api_version: str = Field(default=API_VERSION, description="契约版本（回显）")
    request_id: Optional[str] = Field(default=None, description="调用方传入的追踪号（回显）")
    engine: EngineInfo = Field(description="执行形态与版本")
    answers: Dict[str, Any] = Field(
        description=(
            "每个问题的答案（键与入参 questions 一一对应）。按问法不同包含："
            "choice → choice + probabilities；score → score + legend + probabilities；"
            "noul → noul（P(是)）；三者都有 confidence（把握程度，0~1）"
        ),
        examples=[[{
            "department": {"type": "choice", "choice": "technical", "confidence": 0.3657,
                           "probabilities": {"technical": 0.5786, "billing": 0.0026, "account": 0.4188},
                           "action": {"act_probability": 1.0}},
            "needs_human": {"type": "noul", "noul": 0.2769, "confidence": 0.7231,
                            "action": {"act_probability": 1.0}},
        }][0]],
    )
    usage: Usage = Field(description="运行信息")
    warnings: List[str] = Field(default_factory=list, description="提示，如 state_truncated（情境被截断）")


class ErrorBody(BaseModel):
    code: str = Field(
        description=("错误码：SCHEMA_INVALID(400) / UNAUTHORIZED(401) / OVER_BUDGET(413) / RATE_LIMITED(429) / "
                     "BUSY(503) / MODEL_UNAVAILABLE(503) / TIMEOUT(504) / INTERNAL(500)"),
        examples=["SCHEMA_INVALID"],
    )
    message: str = Field(description="可读的错误说明", examples=["question 'department': choice 标签必须唯一"])
    details: Optional[Dict[str, Any]] = Field(default=None, description="结构化细节（超限字段、仍在推理等）")


class ErrorResponse(BaseModel):
    """统一的错误信封：所有 4xx/5xx 都是这个形状，调用方按 error.code 编程。"""

    api_version: str = Field(default=API_VERSION, description="契约版本")
    request_id: Optional[str] = Field(default=None, description="调用方追踪号（回显）")
    error: ErrorBody = Field(description="错误主体")
