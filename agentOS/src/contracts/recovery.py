"""失败上报、恢复计划和工作流图补丁的共享合同。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .workflow import GraphRef


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FailureEvent(BaseModel):
    """执行部件上报给恢复部件的一次失败事实。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    failure_id: StrictStr = Field(alias="failureId", min_length=1, description="失败事件唯一标识。")
    subject_ref: StrictStr = Field(alias="subjectRef", min_length=1, description="失败执行、节点或资源的稳定引用。")
    failure_type: StrictStr = Field(alias="failureType", min_length=1, description="机器可读的失败分类。")
    message: StrictStr = Field(min_length=1, description="失败的可读说明。")
    retryable: bool = Field(default=False, description="调用方声明该失败是否可重试。")
    occurred_at: datetime = Field(default_factory=_utc_now, alias="occurredAt", description="失败发生的 UTC 时间。")
    details: dict[str, Any] = Field(default_factory=dict, description="不含部件实现对象的失败详情。")


class GraphPatchRef(BaseModel):
    """针对指定工作流图版本的一份可校验补丁引用。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    patch_id: StrictStr = Field(alias="patchId", min_length=1, description="图补丁唯一标识。")
    graph: GraphRef = Field(description="补丁适用的工作流图和版本。")
    uri: StrictStr = Field(min_length=1, description="补丁内容的外部位置。")
    checksum: StrictStr = Field(min_length=1, description="补丁内容的稳定校验和。")


class GraphPatch(BaseModel):
    """A bounded, serializable mutation against one immutable ACG revision."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    patch_id: StrictStr = Field(alias="patchId", min_length=1)
    idempotency_key: StrictStr = Field(alias="idempotencyKey", min_length=1)
    run_id: StrictStr = Field(alias="runId", min_length=1)
    graph_id: StrictStr = Field(alias="graphId", min_length=1)
    base_graph_version: int = Field(alias="baseGraphVersion", ge=1)
    add_nodes: list[dict[str, Any]] = Field(default_factory=list, alias="addNodes")
    add_edges: list[dict[str, Any]] = Field(default_factory=list, alias="addEdges")
    remove_edge_ids: list[StrictStr] = Field(default_factory=list, alias="removeEdgeIds")
    reason: str = ""
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")

    def checksum(self) -> str:
        payload = self.model_dump(by_alias=True, mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class GraphPatchResult(BaseModel):
    """Reference-only result of applying or replaying one graph patch."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    applied: bool
    idempotent_replay: bool = Field(default=False, alias="idempotentReplay")
    graph_version: int = Field(alias="graphVersion", ge=1)
    patch_ref: GraphPatchRef = Field(alias="patchRef")


class RecoveryNodeTemplate(BaseModel):
    """A capability-only node declaration used by a recovery recipe."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    logical_name: StrictStr = Field(alias="logicalName", min_length=1)
    name: StrictStr = Field(min_length=1)
    capability: StrictStr = Field(min_length=1)
    input_spec: dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: dict[str, Any] = Field(default_factory=dict, alias="outputSpec")


class RecoveryRecipe(BaseModel):
    """Versioned bounded recovery policy containing no concrete Agent ID."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recipe_id: StrictStr = Field(alias="recipeId", min_length=1)
    version: StrictStr = Field(min_length=1)
    trigger_failure_types: list[StrictStr] = Field(alias="triggerFailureTypes", min_length=1)
    trigger_reason_codes: list[StrictStr] = Field(default_factory=list, alias="triggerReasonCodes")
    required_capabilities: list[StrictStr] = Field(alias="requiredCapabilities", min_length=1)
    max_applications_per_run: int = Field(default=1, alias="maxApplicationsPerRun", ge=1)
    node_templates: list[RecoveryNodeTemplate] = Field(alias="nodeTemplates", min_length=1)

    def matches(self, failure: FailureEvent) -> bool:
        kinds = {item.strip().lower() for item in self.trigger_failure_types}
        reasons = {item.strip().upper() for item in self.trigger_reason_codes}
        reason = str(failure.details.get("reasonCode") or "").upper()
        return failure.failure_type.strip().lower() in kinds and (
            not reasons or "*" in reasons or reason in reasons
        )


class RecoveryPlan(BaseModel):
    """恢复部件提出的、可由运行时执行的恢复计划。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    plan_id: StrictStr = Field(alias="planId", min_length=1, description="恢复计划唯一标识。")
    failure_id: StrictStr = Field(alias="failureId", min_length=1, description="触发该计划的失败事件标识。")
    strategy: Literal["retry", "rollback", "patch_graph", "abort"] = Field(description="采用的稳定恢复策略。")
    graph_patch: GraphPatchRef | None = Field(default=None, alias="graphPatch", description="图补丁策略使用的补丁引用。")
    steps: list[StrictStr] = Field(default_factory=list, description="由运行时解释的有序恢复步骤。")
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt", description="计划生成的 UTC 时间。")
