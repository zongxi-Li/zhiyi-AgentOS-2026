"""定义受控运行时图补丁的强类型输入、约束与结果。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from components.planner.models import ACGEdge
from components.planner.models import ACGNode, parse_node
from contracts.workflow import utc_now
from components.executor.graph import RuntimeGraph, RuntimeNodeStatus
from components.recovery.runtime_recovery.bindings import ExecutionBinding


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PatchOperationType(str, Enum):
    """运行图补丁允许的受限操作类型，用于验证与重放。"""
    ADD_SUBGRAPH = "ADD_SUBGRAPH"
    RETRY_ALTERNATE_BINDING = "RETRY_ALTERNATE_BINDING"
    ACTIVATE_CONDITIONAL_BRANCH = "ACTIVATE_CONDITIONAL_BRANCH"


class SubgraphInsertionMode(str, Enum):
    """恢复子图相对目标节点的插入位置枚举。"""
    INSERT_BEFORE_TARGET = "INSERT_BEFORE_TARGET"


class PatchBudgetImpact(BaseModel):
    """量化单个补丁对节点、边和重规划预算的影响。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    added_nodes: int = Field(default=0, alias="addedNodes", ge=0)
    replan_depth_increment: int = Field(default=1, alias="replanDepthIncrement", ge=0)


class RuntimeGraphPatch(BaseModel):
    """描述对指定运行图版本执行的有界补丁请求。

    模型承载节点、边、来源事件和幂等信息；验证器负责检查图与预算，模型本身不
    修改运行图。内容和语义哈希可用于检测重放与等价冲突。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    patch_id: str = Field(alias="patchId", min_length=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1)
    run_id: str = Field(alias="runId", min_length=1)
    graph_id: str = Field(alias="graphId", min_length=1)
    base_graph_version: int = Field(alias="baseGraphVersion", ge=1)
    operation_type: PatchOperationType = Field(alias="operationType")
    source_event_id: str = Field(alias="sourceEventId", min_length=1)
    proposal_id: str = Field(alias="proposalId", min_length=1)
    reason: str = ""
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    expected_node_states: dict[str, RuntimeNodeStatus] = Field(
        default_factory=dict,
        alias="expectedNodeStates",
    )
    budget_impact: PatchBudgetImpact = Field(alias="budgetImpact")
    metadata: dict[str, Any] = Field(default_factory=dict)
    insertion_mode: SubgraphInsertionMode = Field(
        default=SubgraphInsertionMode.INSERT_BEFORE_TARGET,
        alias="insertionMode",
    )
    target_node_id: str | None = Field(default=None, alias="targetNodeId")
    replaced_incoming_edge_ids: list[str] = Field(default_factory=list, alias="replacedIncomingEdgeIds")
    add_nodes: list[ACGNode] = Field(default_factory=list, alias="addNodes")
    add_edges: list[ACGEdge] = Field(default_factory=list, alias="addEdges")
    runtime_node_id: str | None = Field(default=None, alias="runtimeNodeId")
    expected_attempt_id: str | None = Field(default=None, alias="expectedAttemptId")
    expected_current_binding_id: str | None = Field(
        default=None, alias="expectedCurrentBindingId"
    )
    new_binding: ExecutionBinding | None = Field(default=None, alias="newBinding")
    excluded_binding_ids: list[str] = Field(default_factory=list, alias="excludedBindingIds")
    control_node_id: str | None = Field(default=None, alias="controlNodeId")
    expected_control_node_state: RuntimeNodeStatus | None = Field(
        default=None, alias="expectedControlNodeState"
    )
    expected_source_output_version: int | None = Field(
        default=None, alias="expectedSourceOutputVersion"
    )
    input_hash: str | None = Field(default=None, alias="inputHash")
    selected_case_key: str | None = Field(default=None, alias="selectedCaseKey")
    selected_edge_ids: list[str] = Field(default_factory=list, alias="selectedEdgeIds")
    terminated_edge_ids: list[str] = Field(default_factory=list, alias="terminatedEdgeIds")
    join_node_id: str | None = Field(default=None, alias="joinNodeId")
    node_state_updates: dict[str, RuntimeNodeStatus] = Field(
        default_factory=dict, alias="nodeStateUpdates"
    )

    @field_validator("add_nodes", mode="before")
    @classmethod
    def _parse_nodes(cls, value):
        return [parse_node(item) for item in (value or [])]

    @model_validator(mode="after")
    def _validate_operation_payload(self):
        if self.operation_type == PatchOperationType.ADD_SUBGRAPH:
            if not self.target_node_id or not self.add_nodes or not self.add_edges:
                raise ValueError("ADD_SUBGRAPH requires targetNodeId, addNodes, and addEdges")
            if self.new_binding is not None or self.runtime_node_id is not None:
                raise ValueError("ADD_SUBGRAPH payload cannot contain binding fields")
        elif self.operation_type == PatchOperationType.RETRY_ALTERNATE_BINDING:
            if not self.runtime_node_id or self.new_binding is None:
                raise ValueError("RETRY_ALTERNATE_BINDING requires runtimeNodeId and newBinding")
            if self.target_node_id or self.add_nodes or self.add_edges or self.replaced_incoming_edge_ids:
                raise ValueError("binding patch cannot contain subgraph fields")
            if self.control_node_id or self.selected_edge_ids or self.terminated_edge_ids:
                raise ValueError("binding patch cannot contain conditional fields")
        elif self.operation_type == PatchOperationType.ACTIVATE_CONDITIONAL_BRANCH:
            if (
                not self.control_node_id
                or self.expected_source_output_version is None
                or not self.input_hash
                or not self.selected_edge_ids
                or not self.terminated_edge_ids
                or not self.join_node_id
            ):
                raise ValueError("conditional patch requires complete decision fields")
            if (
                self.target_node_id
                or self.add_nodes
                or self.add_edges
                or self.replaced_incoming_edge_ids
                or self.new_binding is not None
                or self.runtime_node_id is not None
            ):
                raise ValueError("conditional patch cannot contain subgraph or binding fields")
        return self

    def content_hash(self) -> str:
        """返回包含补丁标识的内容哈希，供精确重放与审计比对。"""
        return _hash(self.model_dump(by_alias=True, mode="json"))

    def semantic_hash(self) -> str:
        """返回忽略请求标识的语义哈希，供等价补丁冲突检测。"""
        payload = self.model_dump(by_alias=True, mode="json")
        for key in (
            "patchId",
            "idempotencyKey",
            "createdAt",
            "sourceEventId",
            "proposalId",
            "reason",
        ):
            payload.pop(key, None)
        return _hash(payload)


class PatchApplyResult(BaseModel):
    """保存补丁实际应用或幂等重放后的版本、检查点和运行图投影。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    applied: bool
    idempotent_replay: bool = Field(default=False, alias="idempotentReplay")
    graph_version: int = Field(alias="graphVersion")
    patch_id: str = Field(alias="patchId")
    checkpoint_id: str | None = Field(default=None, alias="checkpointId")
    runtime_graph: RuntimeGraph = Field(alias="runtimeGraph")


__all__ = [
    "PatchApplyResult",
    "PatchBudgetImpact",
    "PatchOperationType",
    "RuntimeGraphPatch",
    "SubgraphInsertionMode",
]
