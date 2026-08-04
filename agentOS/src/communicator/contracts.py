"""通信器内部的低熵上下文合同。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.communication import ContextPackRef, MessageEnvelope


def estimate_tokens(payload: Any) -> int:
    """提供稳定的相对 Token 度量，避免把具体模型分词器耦合进通信层。"""
    if payload is None:
        return 0
    try:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return max(0, round(len(text) / 3.2))


def input_revision(payload: Any) -> str:
    """为一份已解析输入生成可审计的稳定版本号。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ContextPack(BaseModel):
    """下游步骤的最小充分上下文；data 只能来自字段白名单。"""

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
