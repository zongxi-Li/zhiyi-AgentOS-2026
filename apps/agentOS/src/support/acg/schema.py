"""Stable serialized contracts for Agent Computation Graph blueprints."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

class NodeType(str, Enum):
    """ACG 节点类别；决定节点的序列化模型与下游消费语义。"""
    STEP = "step"
    AGENT = "agent"
    SKILL = "skill"
    MEMORY = "memory"
    EVIDENCE = "evidence"
    CONTROL = "control"


class EdgeType(str, Enum):
    """ACG 有向边类别；只有 ``DEPENDENCY`` 定义执行就绪关系。"""
    DEPENDENCY = "dependency"
    COMMUNICATION = "communication"
    CONTROL_FLOW = "control_flow"
    EXECUTION = "execution"
    WRITE = "write"
    READ = "read"
    SUPPORT = "support"


class ControlType(str, Enum):
    """控制节点的结构类型，用于表达起止、分支、循环、并行或共识。"""
    START = "start"
    END = "end"
    IF = "if"
    LOOP = "loop"
    PARALLEL = "parallel"
    CONSENSUS = "consensus"


class ComplexityLevel(str, Enum):
    """规划阶段估计的任务复杂度分级，不是运行时资源计量。"""
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    EXTREME = "extreme"


class BlueprintStatus(str, Enum):
    """蓝图节点的规划可用性状态，和执行步骤状态相互独立。"""
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class ConditionOperator(str, Enum):
    """条件节点只支持受限操作符，禁止把表达式求值带入规划层。"""
    EQUALS = "EQUALS"
    IN = "IN"
    EXISTS = "EXISTS"
    BOOLEAN = "BOOLEAN"


class ConditionSpec(BaseModel):
    """ACG 条件控制的可序列化合同。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    source_node_id: str = Field(alias="sourceNodeId", min_length=1)
    json_pointer: str = Field(alias="jsonPointer")
    operator: ConditionOperator
    cases: dict[str, str]
    default_edge_id: str | None = Field(default=None, alias="defaultEdgeId")
    value_type: str = Field(default="string", alias="valueType")


class LoopSpec(BaseModel):
    """A bounded loop region with a restricted exit condition."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    body_entry_id: str = Field(alias="bodyEntryId", min_length=1)
    body_exit_id: str = Field(alias="bodyExitId", min_length=1)
    condition: ConditionSpec
    max_iterations: int = Field(alias="maxIterations", ge=1)
    on_limit: Literal["review", "fail"] = Field(default="review", alias="onLimit")


class ParallelSpec(BaseModel):
    """A deterministic fork/join region."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    branch_entry_ids: List[str] = Field(alias="branchEntryIds", min_length=2)
    join_node_id: str = Field(alias="joinNodeId", min_length=1)


class ConsensusSpec(BaseModel):
    """A bounded consensus barrier over committed participant outputs."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    participant_step_ids: List[str] = Field(alias="participantStepIds", min_length=1)
    quorum: int = Field(ge=1)
    strategy: Literal["unanimous", "majority", "auditor"] = "majority"
    timeout_seconds: int = Field(default=300, alias="timeoutSeconds", ge=1)
    on_unresolved: Literal["review", "fail"] = Field(default="review", alias="onUnresolved")



def _node_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class ACGNodeBase(BaseModel):
    """ACG 节点公共基类。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    node_id: str = Field(alias="nodeId")
    node_type: NodeType = Field(alias="nodeType")
    name: str = ""
    description: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_appendix_identity_fields(cls, value: Any) -> Any:
        """Accept appendix-specific identity keys without duplicating graph state."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        node_kind = data.get("nodeType") or data.get("node_type")
        if isinstance(node_kind, NodeType):
            node_kind = node_kind.value
        node_kind = node_kind or {
            "StepNode": "step",
            "AgentNode": "agent",
            "SkillNode": "skill",
            "MemoryNode": "memory",
            "EvidenceNode": "evidence",
            "ControlNode": "control",
        }.get(cls.__name__)
        appendix_id = {
            "step": "stepId",
            "agent": "agentId",
            "skill": "skillId",
            "memory": "memoryId",
            "evidence": "evidenceId",
            "control": "controlId",
        }.get(node_kind)
        appendix_name = {
            "step": "stepName",
            "agent": "agentName",
            "skill": "skillName",
            "memory": "memoryName",
            "evidence": "evidenceName",
        }.get(node_kind)
        if "nodeId" not in data and "node_id" not in data and appendix_id in data:
            data["nodeId"] = data[appendix_id]
        if "name" not in data and appendix_name and appendix_name in data:
            data["name"] = data[appendix_name]
        return data


def _reject_removed_resource_fields(value: Any, fields: set[str], label: str) -> Any:
    if isinstance(value, dict):
        containers = ((value, label), (value.get("metadata"), f"{label} metadata"))
        for container, container_label in containers:
            if not isinstance(container, dict):
                continue
            removed = sorted(fields.intersection(container))
            if removed:
                raise ValueError(
                    f"{container_label} no longer accepts legacy resource fields: {removed}"
                )
    return value


class StepNode(ACGNodeBase):
    """执行步骤节点 ACG 中的最小执行单元。"""

    node_type: Literal[NodeType.STEP] = Field(default=NodeType.STEP, alias="nodeType")
    step_type: str = Field(default="agent", alias="stepType")
    goal: str = ""
    acceptance_criteria: List[str] = Field(default_factory=list, alias="acceptanceCriteria")
    source_refs: List[str] = Field(default_factory=list, alias="sourceRefs")
    logical_role: str = Field(default="task", alias="logicalRole")
    input_spec: Dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: Dict[str, Any] = Field(default_factory=dict, alias="outputSpec")
    # Execution capability requirement. The Agent binding is represented by an EXECUTION edge.
    capability: Optional[str] = None
    timeout: int = 0
    retry_limit: int = Field(default=0, alias="retryLimit")
    priority: int = 0
    status: BlueprintStatus = BlueprintStatus.DRAFT
    review_required: bool = Field(default=False, alias="reviewRequired")

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_resource_fields(cls, value: Any) -> Any:
        return _reject_removed_resource_fields(
            value,
            {
                "agentName", "agent_name", "assignedAgentId", "assigned_agent_id",
                "skillIds", "skill_ids", "memoryIds", "memory_ids",
                "evidenceIds", "evidence_ids",
            },
            "StepNode",
        )

    @computed_field(alias="stepId", return_type=str)
    @property
    def step_id(self) -> str:
        """返回节点标识作为兼容旧合同的 ``stepId`` 视图。"""
        return self.node_id

    @computed_field(alias="stepName", return_type=str)
    @property
    def step_name(self) -> str:
        """返回节点名称作为兼容旧合同的 ``stepName`` 视图。"""
        return self.name


class AgentNode(ACGNodeBase):
    """智能体节点"""

    node_type: Literal[NodeType.AGENT] = Field(default=NodeType.AGENT, alias="nodeType")
    role: str = ""
    model_name: Optional[str] = Field(default=None, alias="modelName")
    capability_tags: List[str] = Field(default_factory=list, alias="capabilityTags")
    max_concurrency: int = Field(default=1, alias="maxConcurrency")
    status: BlueprintStatus = BlueprintStatus.DRAFT
    ephemeral: bool = False  # 动态角色生成器产出的临时角色标记

    @model_validator(mode="before")
    @classmethod
    def _reject_inline_resource_lists(cls, value: Any) -> Any:
        return _reject_removed_resource_fields(
            value, {"skillIds", "skill_ids", "memoryIds", "memory_ids"}, "AgentNode"
        )

    @computed_field(alias="agentId", return_type=str)
    @property
    def agent_id(self) -> str:
        """返回节点标识作为 ``agentId`` 的计算字段。"""
        return self.node_id

    @computed_field(alias="agentName", return_type=str)
    @property
    def agent_name(self) -> str:
        """返回节点名称作为 ``agentName`` 的计算字段。"""
        return self.name


class SkillNode(ACGNodeBase):
    """技能节点"""

    node_type: Literal[NodeType.SKILL] = Field(default=NodeType.SKILL, alias="nodeType")
    skill_type: str = Field(default="generic", alias="skillType")
    input_spec: Dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: Dict[str, Any] = Field(default_factory=dict, alias="outputSpec")
    tool_name: Optional[str] = Field(default=None, alias="toolName")
    version: str = "1.0.0"

    @computed_field(alias="skillId", return_type=str)
    @property
    def skill_id(self) -> str:
        """返回节点标识作为 ``skillId`` 的计算字段。"""
        return self.node_id

    @computed_field(alias="skillName", return_type=str)
    @property
    def skill_name(self) -> str:
        """返回节点名称作为 ``skillName`` 的计算字段。"""
        return self.name


class MemoryNode(ACGNodeBase):
    """记忆节点 提供长程上下文连续性。"""

    node_type: Literal[NodeType.MEMORY] = Field(default=NodeType.MEMORY, alias="nodeType")
    memory_type: str = Field(default="working", alias="memoryType")
    storage_type: str = Field(default="inline", alias="storageType")
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    retention_policy: str = Field(default="task", alias="retentionPolicy")

    @computed_field(alias="memoryId", return_type=str)
    @property
    def memory_id(self) -> str:
        """返回节点标识作为 ``memoryId`` 的计算字段。"""
        return self.node_id

    @computed_field(alias="memoryName", return_type=str)
    @property
    def memory_name(self) -> str:
        """返回节点名称作为 ``memoryName`` 的计算字段。"""
        return self.name


class EvidenceNode(ACGNodeBase):
    """证据节点 承载可信交付与审计依据。"""

    node_type: Literal[NodeType.EVIDENCE] = Field(default=NodeType.EVIDENCE, alias="nodeType")
    evidence_type: str = Field(default="document", alias="evidenceType")
    source: str = ""
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    producer_step_id: Optional[str] = Field(default=None, alias="producerStepId")

    @model_validator(mode="before")
    @classmethod
    def _reject_metadata_producer_fallback(cls, value: Any) -> Any:
        if isinstance(value, dict):
            metadata = value.get("metadata")
            if isinstance(metadata, dict) and (
                "producerStepId" in metadata or "producer_step_id" in metadata
            ):
                raise ValueError(
                    "EvidenceNode producer must use the typed producerStepId field"
                )
        return value

    @computed_field(alias="evidenceId", return_type=str)
    @property
    def evidence_id(self) -> str:
        """返回节点标识作为 ``evidenceId`` 的计算字段。"""
        return self.node_id

    @computed_field(alias="evidenceName", return_type=str)
    @property
    def evidence_name(self) -> str:
        """返回节点名称作为 ``evidenceName`` 的计算字段。"""
        return self.name


class ControlNode(ACGNodeBase):
    """控制节点 实现条件/循环/并行/共识。"""

    node_type: Literal[NodeType.CONTROL] = Field(default=NodeType.CONTROL, alias="nodeType")
    control_type: ControlType = Field(default=ControlType.START, alias="controlType")
    condition: str = ""
    condition_spec: Optional[ConditionSpec] = Field(default=None, alias="conditionSpec")
    branch_edge_ids: List[str] = Field(default_factory=list, alias="branchEdgeIds")
    join_node_id: Optional[str] = Field(default=None, alias="joinNodeId")
    loop_spec: Optional[LoopSpec] = Field(default=None, alias="loopSpec")
    parallel_spec: Optional[ParallelSpec] = Field(default=None, alias="parallelSpec")
    consensus_spec: Optional[ConsensusSpec] = Field(default=None, alias="consensusSpec")

    @computed_field(alias="controlId", return_type=str)
    @property
    def control_id(self) -> str:
        """返回节点标识作为 ``controlId`` 的计算字段。"""
        return self.node_id


ACGNode = Union[StepNode, AgentNode, SkillNode, MemoryNode, EvidenceNode, ControlNode]

_NODE_MODEL_BY_TYPE = {
    NodeType.STEP: StepNode,
    NodeType.AGENT: AgentNode,
    NodeType.SKILL: SkillNode,
    NodeType.MEMORY: MemoryNode,
    NodeType.EVIDENCE: EvidenceNode,
    NodeType.CONTROL: ControlNode,
}


def parse_node(data: Any) -> ACGNode:
    """根据 nodeType 把 dict 解析为对应的节点模型。"""
    if isinstance(data, ACGNodeBase):
        return data  # type: ignore[return-value]
    if not isinstance(data, dict):
        raise TypeError(f"ACG node must be a dict, got {type(data)!r}")
    raw_type = data.get("nodeType") or data.get("node_type")
    node_type = NodeType(raw_type)
    model = _NODE_MODEL_BY_TYPE[node_type]
    return model.model_validate(data)


"""
    ACG 边定义
"""


from enum import Enum
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

class EdgeActivation(str, Enum):
    """控制流边的运行时激活状态；终止边不得再次参与路由。"""
    INACTIVE = "inactive"
    ACTIVE = "active"
    TERMINATED = "terminated"


def _edge_id() -> str:
    return f"edge_{uuid4().hex[:10]}"


class ACGEdge(BaseModel):
    """ACG 边。统一描述依赖、通信、控制流等多种关系。

    - DEPENDENCY 边：执行器据此计算就绪集（source 完成后 target 才可执行）。
    - COMMUNICATION 边：通信器据此装配下游输入上下文。
    - CONTROL_FLOW 边：由 Control 节点驱动，可携带激活 condition。
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    edge_id: str = Field(default_factory=_edge_id, alias="edgeId")
    source_id: str = Field(alias="sourceId")
    target_id: str = Field(alias="targetId")
    edge_type: EdgeType = Field(default=EdgeType.DEPENDENCY, alias="edgeType")
    condition: str = ""
    activation: EdgeActivation = EdgeActivation.ACTIVE
    # 通信边可声明下游需要从上游 output 提取哪些字段（低熵“按需投递”清单）
    data_fields: list[str] = Field(default_factory=list, alias="dataFields")
    metadata: Dict[str, Any] = Field(default_factory=dict)


"""ACGBlueprint 智能体计算蓝图

规划器的最终产物，也是执行器、通信器、记忆器、审计器共同消费的唯一权威总规划图。

蓝图同时承载图级算法：环检测、就绪集计算、悬空依赖检查、拓扑分析。
这些算法是执行器“就绪集调度”和规划器“图验证”的基础。
"""


from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RuntimeBlueprintSpec(BaseModel):
    """智能体计算图蓝图（设计时静态图）。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    graph_id: str = Field(default_factory=lambda: f"acg_{uuid4().hex[:12]}", alias="graphId")
    mission_id: Optional[str] = Field(default=None, alias="missionId")
    version: int = 1
    objective: str = ""
    complexity_level: ComplexityLevel = Field(default=ComplexityLevel.SIMPLE, alias="complexityLevel")
    priority: int = 0
    nodes: List[ACGNode] = Field(default_factory=list)
    edges: List[ACGEdge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=_utc_now, alias="updatedAt")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("nodes", mode="before")
    @classmethod
    def _coerce_nodes(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [parse_node(item) for item in value]
        return value

    # ------------------------------------------------------------------
    # 基础访问
    # ------------------------------------------------------------------
    @property
    def node_count(self) -> int:
        """返回当前节点数，时间复杂度为 ``O(1)``。"""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """返回当前边数，时间复杂度为 ``O(1)``。"""
        return len(self.edges)

    def get_node(self, node_id: str) -> ACGNode:
        """顺序查找节点，时间复杂度 ``O(V)``；不存在时抛出 ``KeyError``。"""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(f"ACG node not found: {node_id}")

    def has_node(self, node_id: str) -> bool:
        """判断节点是否存在，线性扫描当前节点列表，复杂度 ``O(V)``。"""
        return any(node.node_id == node_id for node in self.nodes)

    def step_nodes(self) -> List[StepNode]:
        """按蓝图原始节点顺序返回全部步骤节点，复杂度 ``O(V)``。"""
        return [n for n in self.nodes if n.node_type == NodeType.STEP]  # type: ignore[misc]

    def nodes_of_type(self, node_type: NodeType) -> List[ACGNode]:
        """按原始顺序筛选指定类别节点，复杂度 ``O(V)``。"""
        return [n for n in self.nodes if n.node_type == node_type]

    def edges_of_type(self, edge_type: EdgeType) -> List[ACGEdge]:
        """按原始顺序筛选指定类别边，复杂度 ``O(E)``。"""
        return [e for e in self.edges if e.edge_type == edge_type]

    def agent_bindings_by_step(self) -> Dict[str, List[AgentNode]]:
        """Return canonical AgentNode bindings declared by EXECUTION edges."""
        bindings: Dict[str, List[AgentNode]] = {}
        for edge in self.edges_of_type(EdgeType.EXECUTION):
            agent = self.get_node(edge.source_id)
            if isinstance(agent, AgentNode):
                bindings.setdefault(edge.target_id, []).append(agent)
        return bindings

    def incoming(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[ACGEdge]:
        """返回指向节点的边，可按类别过滤，结果保持边列表顺序，复杂度 ``O(E)``。"""
        return [
            e for e in self.edges
            if e.target_id == node_id and (edge_type is None or e.edge_type == edge_type)
        ]

    def outgoing(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[ACGEdge]:
        """返回从节点出发的边，可按类别过滤，结果保持边列表顺序，复杂度 ``O(E)``。"""
        return [
            e for e in self.edges
            if e.source_id == node_id and (edge_type is None or e.edge_type == edge_type)
        ]

    def dependency_sources(self, node_id: str) -> List[str]:
        """返回某节点在 DEPENDENCY 边上的所有前驱节点 id。"""
        return [e.source_id for e in self.incoming(node_id, EdgeType.DEPENDENCY)]

    def touch(self) -> None:
        """更新蓝图时间戳及节点/边计数元数据；仅修改当前蓝图对象。"""
        self.updated_at = _utc_now()
        self.metadata["nodeCount"] = self.node_count
        self.metadata["edgeCount"] = self.edge_count


"""ACG 图算法：环检测、拓扑排序、悬空依赖检查、就绪集计算。

这些算法服务两处：
1. 规划器在交付蓝图前做图级验证（非循环性、无悬空依赖）。
2. 执行器在运行时按 DEPENDENCY 边计算“就绪集”，驱动并行调度。

仅依赖 DEPENDENCY 边构建执行 DAG；其它边（通信、记忆读写、证据支撑）
不影响执行先后，由通信器/记忆器/审计器分别消费。
"""


from typing import Dict, List, Set



# Legacy name retained for Planner, plugin, and persisted payload compatibility.
ACGBlueprint = RuntimeBlueprintSpec


class ACGValidationError(ValueError):
    """An ACG structural or graph validation failure."""


__all__ = [
    "ACGBlueprint", "RuntimeBlueprintSpec", "ACGEdge", "ACGNode", "ACGNodeBase",
    "ACGValidationError", "AgentNode", "BlueprintStatus", "ComplexityLevel",
    "ConditionOperator", "ConditionSpec", "ControlNode", "ControlType",
    "EdgeActivation", "EdgeType", "EvidenceNode", "MemoryNode", "NodeType",
    "LoopSpec", "ParallelSpec", "ConsensusSpec", "SkillNode", "StepNode", "parse_node",
]
