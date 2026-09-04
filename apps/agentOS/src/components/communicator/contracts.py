"""通信器内部的低熵上下文合同。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.communication import ContextPackRef, MessageEnvelope


def estimate_tokens(payload: Any) -> int:
    """以规范文本长度估算稳定的相对 Token 数。

    ``None`` 返回零，其余对象优先按排序 JSON 编码，失败时退回 ``str``；结果仅
    用于预算排序，不能替代模型分词器计费。时间与空间复杂度随序列化大小 O(n)。
    """
    if payload is None:
        return 0
    try:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return max(0, round(len(text) / 3.2))


def input_revision(payload: Any) -> str:
    """为已解析输入计算规范 JSON 的 SHA-256 版本标识。

    映射键排序且使用固定分隔符，因此等价输入得到稳定摘要；不可原生编码的值
    转为字符串。函数无副作用，时间和额外空间随编码大小均为 O(n)。
    """
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ContextPack(BaseModel):
    """描述可投递给下游步骤的最小充分、可审计上下文。

    ``data`` 与 ``source_data`` 只能来自上游字段白名单；合同状态、缺失字段、
    Token 统计和输入版本共同记录装配边界。模型禁止额外字段，调用方负责确保
    同一包的账本事件与内容保持一致。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    run_id: str = Field(alias="runId")
    step_id: str = Field(alias="stepId")
    objective: str = ""
    step_goal: str = Field(default="", alias="stepGoal")
    data: dict[str, Any] = Field(default_factory=dict)
    source_data: dict[str, dict[str, Any]] = Field(default_factory=dict, alias="sourceData")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")
    missing_fields: list[str] = Field(default_factory=list, alias="missingFields")
    contract_status: str = Field(default="valid", alias="contractStatus")
    tokens_delivered: int = Field(default=0, alias="tokensDelivered")
    tokens_available: int = Field(default=0, alias="tokensAvailable")
    saving_ratio: float = Field(default=0.0, alias="savingRatio")
    source_step_ids: list[str] = Field(default_factory=list, alias="sourceStepIds")
    graph_version: int = Field(default=0, alias="graphVersion")
    attempt_id: str = Field(default="", alias="attemptId")
    binding_id: str = Field(default="", alias="bindingId")
    input_revision: str = Field(default="", alias="inputRevision")


__all__ = ["ContextPackRef", "MessageEnvelope", "ContextPack", "estimate_tokens", "input_revision"]
