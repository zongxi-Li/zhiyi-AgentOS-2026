"""执行器拥有的运行图模型与确定性图算法。

本模块只保存可序列化的运行时快照。规划器交付的节点、边可以是合同对象或
字典；执行器在边界处复制它们，因此不会反向依赖 ``core`` 的 ACG 实现。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: Any) -> str:
    """用稳定 JSON 表示图结构，供持久化与重放比对。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RuntimeNodeStatus(str, Enum):
    """执行节点的最小状态词表，不泄漏旧运行时枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SKIPPED_BY_CONDITION = "skipped_by_condition"


class RuntimeNodeActivation(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"


class RuntimeEventType(str, Enum):
    BINDING_UNAVAILABLE = "BINDING_UNAVAILABLE"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    INPUT_CONTRACT_VIOLATION = "INPUT_CONTRACT_VIOLATION"
    OUTPUT_CONTRACT_VIOLATION = "OUTPUT_CONTRACT_VIOLATION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    STEP_EXECUTION_FAILED = "STEP_EXECUTION_FAILED"


class RuntimeEventStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"


class RuntimeEdge(BaseModel):
    """执行图边的自包含表示；边类型保持字符串以兼容规划合同。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    edge_id: str = Field(alias="edgeId")
    source_id: str = Field(alias="sourceId")
    target_id: str = Field(alias="targetId")
    edge_type: str = Field(default="dependency", alias="edgeType")
    condition: str = ""
    activation: RuntimeNodeActivation = RuntimeNodeActivation.ACTIVE
    data_fields: list[str] = Field(default_factory=list, alias="dataFields")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    event_id: str = Field(alias="eventId")
    idempotency_key: str = Field(alias="idempotencyKey")
    run_id: str = Field(alias="runId")
    graph_id: str = Field(alias="graphId")
    graph_version: int = Field(alias="graphVersion", ge=1)
    event_type: RuntimeEventType = Field(alias="eventType")
    runtime_node_id: str = Field(alias="runtimeNodeId")
    attempt_id: str = Field(alias="attemptId")
    binding_id: str = Field(default="", alias="bindingId")
    source_trace_event_id: str | None = Field(default=None, alias="sourceTraceEventId")
    payload: dict[str, Any] = Field(default_factory=dict)
    classification_version: str = Field(default="1", alias="classificationVersion")
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")
    status: RuntimeEventStatus = RuntimeEventStatus.PENDING
    status_reason: str = Field(default="", alias="statusReason")

    @property
    def reason_code(self) -> str:
        return str(self.payload.get("reasonCode") or self.event_type.value).strip().upper()

    @property
    def target_node_id(self) -> str:
        return str(self.payload.get("targetNodeId") or self.runtime_node_id)


class RuntimePatchBudget(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    max_graph_patches: int = Field(default=3, alias="maxGraphPatches", ge=0)
    max_added_nodes_per_patch: int = Field(default=4, alias="maxAddedNodesPerPatch", ge=0)
    max_total_runtime_nodes: int = Field(default=20, alias="maxTotalRuntimeNodes", ge=1)
    max_replan_depth: int = Field(default=2, alias="maxReplanDepth", ge=0)
    current_replan_depth: int = Field(default=0, alias="currentReplanDepth", ge=0)


class RuntimeAttempt(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    attempt_id: str = Field(default_factory=lambda: f"attempt_{uuid4().hex}", alias="attemptId")
    attempt_number: int = Field(alias="attemptNumber", ge=1)
    graph_version: int = Field(alias="graphVersion", ge=1)
    binding_id: str = Field(default="", alias="bindingId")
    agent_name: str = Field(default="", alias="agentName")
    model_name: str = Field(default="", alias="modelName")
    status: RuntimeNodeStatus = RuntimeNodeStatus.RUNNING
    started_at: datetime = Field(default_factory=_utc_now, alias="startedAt")
    ended_at: datetime | None = Field(default=None, alias="endedAt")
    resolved_input: dict[str, Any] = Field(default_factory=dict, alias="resolvedInput")
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    trace_context: dict[str, Any] = Field(default_factory=dict, alias="traceContext")
    logical_completion_accepted: bool = Field(default=True, alias="logicalCompletionAccepted")
    runtime_event_ids: list[str] = Field(default_factory=list, alias="runtimeEventIds")


class RuntimeNode(BaseModel):
    """节点定义的副本及其唯一可变执行状态。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    node_id: str = Field(alias="nodeId")
    node_type: str = Field(alias="nodeType")
    spec: dict[str, Any] = Field(default_factory=dict)
    status: RuntimeNodeStatus = RuntimeNodeStatus.PENDING
    activation: RuntimeNodeActivation = RuntimeNodeActivation.ACTIVE
    current_binding: dict[str, Any] | None = Field(default=None, alias="currentBinding")
    binding_candidates: list[dict[str, Any]] = Field(default_factory=list, alias="bindingCandidates")
    binding_history: list[dict[str, Any]] = Field(default_factory=list, alias="bindingHistory")
    binding_switch_count: int = Field(default=0, alias="bindingSwitchCount", ge=0)
    attempts: list[RuntimeAttempt] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict)
    output_version: int = Field(default=0, alias="outputVersion", ge=0)
    error: str | None = None
    source_patch_id: str | None = Field(default=None, alias="sourcePatchId")
    created_graph_version: int = Field(default=1, alias="createdGraphVersion", ge=1)
    updated_at: datetime = Field(default_factory=_utc_now, alias="updatedAt")

    @classmethod
    def from_acg_node(cls, node: Any, *, graph_version: int, source_patch_id: str | None = None) -> "RuntimeNode":
        """接收任意规划节点，深拷贝为执行器拥有的普通字典。"""
        raw = node.model_dump(by_alias=True, mode="json") if hasattr(node, "model_dump") else dict(node)
        node_id = str(raw.get("nodeId") or raw.get("node_id"))
        node_type = str(raw.get("nodeType") or raw.get("node_type") or "step")
        binding = {
            "assignedAgentId": raw.get("assignedAgentId"), "agentName": raw.get("agentName"),
            "capability": raw.get("capability"), "skillIds": list(raw.get("skillIds") or []),
        } if node_type == "step" else None
        return cls(nodeId=node_id, nodeType=node_type, spec=raw, currentBinding=binding,
                   sourcePatchId=source_patch_id, createdGraphVersion=graph_version)


class AppliedPatchRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    patch_id: str = Field(alias="patchId")
    idempotency_key: str = Field(alias="idempotencyKey")
    content_hash: str = Field(alias="contentHash")
    semantic_hash: str = Field(alias="semanticHash")
    operation_type: str = Field(alias="operationType")
    base_graph_version: int = Field(alias="baseGraphVersion")
    result_graph_version: int = Field(alias="resultGraphVersion")
    source_event_id: str = Field(alias="sourceEventId")
    checkpoint_id: str | None = Field(default=None, alias="checkpointId")
    applied_at: datetime = Field(default_factory=_utc_now, alias="appliedAt")


class RuntimeGraph(BaseModel):
    """单次运行的权威、可版本化执行图。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    run_id: str = Field(alias="runId")
    graph_id: str = Field(alias="graphId")
    source_blueprint_version: int = Field(alias="sourceBlueprintVersion", ge=1)
    graph_version: int = Field(default=1, alias="graphVersion", ge=1)
    nodes: list[RuntimeNode] = Field(default_factory=list)
    edges: list[RuntimeEdge] = Field(default_factory=list)
    processed_event_ids: list[str] = Field(default_factory=list, alias="processedEventIds")
    runtime_events: list[RuntimeEvent] = Field(default_factory=list, alias="runtimeEvents")
    pending_runtime_event_ids: list[str] = Field(default_factory=list, alias="pendingRuntimeEventIds")
    event_to_patch: dict[str, str] = Field(default_factory=dict, alias="eventToPatch")
    applied_recipe_scopes: list[str] = Field(default_factory=list, alias="appliedRecipeScopes")
    applied_patch_ids: list[str] = Field(default_factory=list, alias="appliedPatchIds")
    applied_patch_idempotency_keys: list[str] = Field(default_factory=list, alias="appliedPatchIdempotencyKeys")
    applied_patches: list[AppliedPatchRecord] = Field(default_factory=list, alias="appliedPatches")
    branch_decisions: list[Any] = Field(default_factory=list, alias="branchDecisions")
    patch_budget: RuntimePatchBudget = Field(default_factory=RuntimePatchBudget, alias="patchBudget")
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=_utc_now, alias="updatedAt")

    @classmethod
    def from_blueprint(cls, *, run_id: str, blueprint: Any, agent_registry: Any | None = None, domain: str = "") -> "RuntimeGraph":
        raw_nodes = list(getattr(blueprint, "nodes", []) or [])
        raw_edges = list(getattr(blueprint, "edges", []) or [])
        graph = cls(runId=run_id, graphId=str(getattr(blueprint, "graph_id", "")),
                    sourceBlueprintVersion=int(getattr(blueprint, "version", 1)),
                    nodes=[RuntimeNode.from_acg_node(node, graph_version=1) for node in raw_nodes],
                    edges=[RuntimeEdge.model_validate(edge.model_dump(by_alias=True) if hasattr(edge, "model_dump") else edge) for edge in raw_edges])
        for node in graph.nodes:
            if node.node_type == "control" and str(node.spec.get("controlType") or "") == "if":
                for edge in graph.edges:
                    if edge.edge_id in set(node.spec.get("branchEdgeIds") or []):
                        edge.activation = RuntimeNodeActivation.INACTIVE
        graph.enrich_bindings(agent_registry=agent_registry, domain=domain)
        return graph

    def get_node(self, node_id: str) -> RuntimeNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(f"runtime node not found: {node_id}")

    def has_node(self, node_id: str) -> bool:
        return any(node.node_id == node_id for node in self.nodes)

    def effective_edges(self, edge_type: Any | None = None) -> list[RuntimeEdge]:
        wanted = getattr(edge_type, "value", edge_type)
        return [edge for edge in self.edges if not edge.metadata.get("supersededByPatchId") and (wanted is None or edge.edge_type == wanted)]

    def dependency_sources(self, node_id: str) -> list[str]:
        return [edge.source_id for edge in self.effective_edges() if edge.target_id == node_id
                and edge.edge_type in {"dependency", "control_flow"} and edge.activation == RuntimeNodeActivation.ACTIVE
                and self.get_node(edge.source_id).status != RuntimeNodeStatus.SKIPPED_BY_CONDITION]

    def ready_set(self) -> list[RuntimeNode]:
        """计算就绪集：仅活跃 step、所有有效前驱成功，并稳定排序。"""
        ready: list[RuntimeNode] = []
        for node in self.nodes:
            if node.node_type != "step" or node.activation != RuntimeNodeActivation.ACTIVE or node.status not in {RuntimeNodeStatus.PENDING, RuntimeNodeStatus.RETRYING}:
                continue
            incoming = [edge for edge in self.effective_edges() if edge.target_id == node.node_id and edge.edge_type in {"dependency", "control_flow"}]
            if any(edge.activation == RuntimeNodeActivation.INACTIVE for edge in incoming):
                continue
            if all(self.get_node(source).status == RuntimeNodeStatus.COMPLETED for source in self.dependency_sources(node.node_id)):
                ready.append(node)
        return sorted(ready, key=lambda item: (-int(item.spec.get("priority", 0)), item.node_id))

    def topological_order(self) -> list[str]:
        """对有效依赖边进行 Kahn 排序；环路用 ValueError 明确拒绝。"""
        node_ids = {node.node_id for node in self.nodes}
        parents = {node_id: set() for node_id in node_ids}
        children = {node_id: set() for node_id in node_ids}
        for edge in self.effective_edges():
            if edge.edge_type in {"dependency", "control_flow"} and edge.activation == RuntimeNodeActivation.ACTIVE:
                parents[edge.target_id].add(edge.source_id); children[edge.source_id].add(edge.target_id)
        queue = sorted(node_id for node_id, sources in parents.items() if not sources)
        ordered: list[str] = []
        while queue:
            current = queue.pop(0); ordered.append(current)
            for target in sorted(children[current]):
                parents[target].remove(current)
                if not parents[target]: queue.append(target)
            queue.sort()
        if len(ordered) != len(node_ids): raise ValueError("runtime graph contains a dependency cycle")
        return ordered

    def resolve_ready_control_nodes(self) -> bool:
        """无条件控制节点在依赖完成后自动结束；IF 必须由条件决策显式激活。"""
        changed = False
        for node in self.nodes:
            if node.node_type == "control" and node.status == RuntimeNodeStatus.PENDING and str(node.spec.get("controlType") or "") != "if":
                if all(self.get_node(source).status == RuntimeNodeStatus.COMPLETED for source in self.dependency_sources(node.node_id)):
                    node.status = RuntimeNodeStatus.COMPLETED; node.updated_at = _utc_now(); changed = True
        return changed

    def activate_condition(self, control_node_id: str, selected_edge_ids: Iterable[str]) -> None:
        """一次条件决策只能按排序后的 edge id 激活，避免分支选择依赖遍历顺序。"""
        selected = set(selected_edge_ids)
        control = self.get_node(control_node_id)
        declared = set(control.spec.get("branchEdgeIds") or [])
        if not selected <= declared: raise ValueError("selected conditional edge is not declared by control node")
        for edge in self.edges:
            if edge.edge_id in declared: edge.activation = RuntimeNodeActivation.ACTIVE if edge.edge_id in selected else RuntimeNodeActivation.TERMINATED
        control.status = RuntimeNodeStatus.COMPLETED; control.updated_at = _utc_now()

    def has_waiting_review(self) -> bool: return any(node.status == RuntimeNodeStatus.WAITING_REVIEW for node in self.nodes)
    def has_runnable_nodes(self) -> bool: return bool(self.ready_set())
    def has_running_nodes(self) -> bool: return any(node.status == RuntimeNodeStatus.RUNNING for node in self.nodes)
    def all_steps_completed(self) -> bool:
        steps = [node for node in self.nodes if node.node_type == "step"]
        return bool(steps) and all(node.status in {RuntimeNodeStatus.COMPLETED, RuntimeNodeStatus.SKIPPED_BY_CONDITION} for node in steps)
    def is_terminal(self) -> bool:
        return bool(self.nodes) and all(node.status in {RuntimeNodeStatus.COMPLETED, RuntimeNodeStatus.FAILED, RuntimeNodeStatus.CANCELLED, RuntimeNodeStatus.SKIPPED_BY_CONDITION} for node in self.nodes if node.node_type == "step")
    def branch_decision_for(self, control_node_id: str) -> Any | None:
        return next((item for item in self.branch_decisions if getattr(item, "control_node_id", None) == control_node_id), None)
    def patch_record_by_id(self, patch_id: str) -> AppliedPatchRecord | None: return next((item for item in self.applied_patches if item.patch_id == patch_id), None)
    def patch_record_by_idempotency_key(self, key: str) -> AppliedPatchRecord | None: return next((item for item in self.applied_patches if item.idempotency_key == key), None)
    def runtime_event_by_id(self, event_id: str) -> RuntimeEvent | None: return next((item for item in self.runtime_events if item.event_id == event_id), None)
    @staticmethod
    def recipe_scope(recipe_id: str, target_node_id: str) -> str: return f"{recipe_id}::{target_node_id}"

    def enrich_bindings(self, *, agent_registry: Any | None, domain: str) -> None:
        """只保留蓝图中的绑定；候选绑定由 scheduler 以资源合同独立决定。"""
        del agent_registry, domain
        for node in self.nodes:
            if node.node_type == "step" and node.current_binding is None:
                node.current_binding = {"assignedAgentId": node.spec.get("assignedAgentId"), "agentName": node.spec.get("agentName"), "capability": node.spec.get("capability")}

    def structure_hash(self) -> str:
        return _canonical_hash({"graphId": self.graph_id, "graphVersion": self.graph_version,
                                "nodes": [node.spec for node in self.nodes],
                                "edges": [edge.model_dump(by_alias=True, mode="json") for edge in self.edges],
                                "appliedPatchIds": self.applied_patch_ids})


def ready_set(dependencies: dict[str, set[str]], completed: set[str]) -> list[str]:
    """兼容简单依赖映射的纯就绪集算法，输出稳定。"""
    return sorted(node for node, required in dependencies.items() if node not in completed and required <= completed)


__all__ = ["AppliedPatchRecord", "RuntimeAttempt", "RuntimeEdge", "RuntimeEvent", "RuntimeEventStatus", "RuntimeEventType", "RuntimeGraph", "RuntimeNode", "RuntimeNodeActivation", "RuntimeNodeStatus", "RuntimePatchBudget", "ready_set"]
