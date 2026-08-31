"""
    ACG 节点定义
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator



# ACG 的类型词表归属于规划器；执行器只消费已经序列化的图合同。
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


class ConditionEvaluationError(ValueError):
    """图校验发现条件分支配置不合法时返回可识别错误码。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def conditional_branch_exclusive_nodes(graph: Any, control_node: Any) -> dict[str, set[str]]:
    """在线性时间 O(V+E) 内验证各条件分支在汇合点前没有共享节点。"""
    edges = {edge.edge_id: edge for edge in graph.edges}
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.edge_type == EdgeType.DEPENDENCY:
            adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    join_id = control_node.join_node_id
    if not join_id:
        raise ConditionEvaluationError("CONDITIONAL_JOIN_MISSING", control_node.node_id)
    branches: dict[str, set[str]] = {}
    for edge_id in control_node.branch_edge_ids:
        edge = edges.get(edge_id)
        if edge is None or edge.source_id != control_node.node_id:
            raise ConditionEvaluationError("CONDITIONAL_BRANCH_EDGE_INVALID", edge_id)
        visited: set[str] = set()
        frontier = [edge.target_id]
        while frontier:
            node_id = frontier.pop()
            if node_id == join_id or node_id in visited:
                continue
            visited.add(node_id)
            frontier.extend(adjacency.get(node_id, []))
        branches[edge_id] = visited
    branch_sets = list(branches.values())
    for index, nodes in enumerate(branch_sets):
        if any(nodes & other for other in branch_sets[index + 1:]):
            raise ConditionEvaluationError("CONDITIONAL_BRANCH_SHARED_NODE", "branches share nodes before join")
    return branches


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
    # 执行绑定：谁来执行、用什么技能
    assigned_agent_id: Optional[str] = Field(default=None, alias="assignedAgentId")
    agent_name: Optional[str] = Field(default=None, alias="agentName")
    capability: Optional[str] = None
    skill_ids: List[str] = Field(default_factory=list, alias="skillIds")
    memory_ids: List[str] = Field(default_factory=list, alias="memoryIds")
    evidence_ids: List[str] = Field(default_factory=list, alias="evidenceIds")
    timeout: int = 0
    retry_limit: int = Field(default=0, alias="retryLimit")
    priority: int = 0
    status: BlueprintStatus = BlueprintStatus.DRAFT
    review_required: bool = Field(default=False, alias="reviewRequired")

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
    skill_ids: List[str] = Field(default_factory=list, alias="skillIds")
    memory_ids: List[str] = Field(default_factory=list, alias="memoryIds")
    max_concurrency: int = Field(default=1, alias="maxConcurrency")
    status: BlueprintStatus = BlueprintStatus.DRAFT
    ephemeral: bool = False  # 动态角色生成器产出的临时角色标记

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

def check_contract_schema(schema: Dict[str, Any], *, label: str) -> None:
    """检查规划输出合同的最小形状，复杂 JSON Schema 交由适配器层扩展。

    这里保留图验证所需的安全下限，避免规划器重新依赖历史数据合同实现。
    """
    if not isinstance(schema, dict):
        raise ACGValidationError(f"{label} contract must be an object")


# 旧名称保留给已有 Planner、插件与持久化载荷；新边界代码使用 RuntimeBlueprintSpec。
ACGBlueprint = RuntimeBlueprintSpec


class ACGValidationError(ValueError):
    """ACG 图结构非法（成环或悬空依赖）。"""


def _dependency_adjacency(blueprint: ACGBlueprint) -> Dict[str, List[str]]:
    """构建仅含 STEP/CONTROL 节点的 DEPENDENCY 邻接表（source -> [targets]）。"""
    executable_ids = {
        n.node_id for n in blueprint.nodes
        if n.node_type in {NodeType.STEP, NodeType.CONTROL}
    }
    adjacency: Dict[str, List[str]] = {nid: [] for nid in executable_ids}
    for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY):
        if edge.source_id in executable_ids and edge.target_id in executable_ids:
            adjacency[edge.source_id].append(edge.target_id)
    return adjacency


def detect_cycle(blueprint: ACGBlueprint) -> List[str]:
    """检测 DEPENDENCY 子图是否成环。返回构成环的节点 id 列表（无环则空）。"""
    adjacency = _dependency_adjacency(blueprint)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {nid: WHITE for nid in adjacency}
    stack: List[str] = []

    def visit(node_id: str) -> List[str]:
        color[node_id] = GRAY
        stack.append(node_id)
        for nxt in adjacency.get(node_id, []):
            if color.get(nxt, WHITE) == GRAY:
                # 回边：截取从 nxt 到当前的栈片段作为环
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if color.get(nxt, WHITE) == WHITE:
                found = visit(nxt)
                if found:
                    return found
        color[node_id] = BLACK
        stack.pop()
        return []

    for nid in adjacency:
        if color[nid] == WHITE:
            cycle = visit(nid)
            if cycle:
                return cycle
    return []


def topological_order(blueprint: ACGBlueprint) -> List[str]:
    """Kahn 算法对 DEPENDENCY 子图做拓扑排序。成环则抛 ACGValidationError。"""
    adjacency = _dependency_adjacency(blueprint)
    indegree: Dict[str, int] = {nid: 0 for nid in adjacency}
    for targets in adjacency.values():
        for t in targets:
            indegree[t] = indegree.get(t, 0) + 1

    queue = [nid for nid, deg in indegree.items() if deg == 0]
    order: List[str] = []
    while queue:
        queue.sort()  # 稳定输出，便于测试
        node_id = queue.pop(0)
        order.append(node_id)
        for nxt in adjacency.get(node_id, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(adjacency):
        raise ACGValidationError(f"ACG contains a cycle; topological sort impossible. cycle={detect_cycle(blueprint)}")
    return order


def find_dangling_dependencies(blueprint: ACGBlueprint) -> List[str]:
    """返回引用了不存在节点的 DEPENDENCY 边 id 列表。"""
    dangling: List[str] = []
    for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY):
        if not blueprint.has_node(edge.source_id) or not blueprint.has_node(edge.target_id):
            dangling.append(edge.edge_id)
    return dangling


def _has_dependency_path(blueprint: ACGBlueprint, source_id: str, target_id: str) -> bool:
    adjacency = _dependency_adjacency(blueprint)
    seen: Set[str] = set()
    frontier = [source_id]
    while frontier:
        current = frontier.pop()
        if current == target_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(adjacency.get(current, []))
    return False


def _validate_edge_endpoints(blueprint: ACGBlueprint) -> None:
    allowed = {
        EdgeType.DEPENDENCY: ({NodeType.STEP, NodeType.CONTROL}, {NodeType.STEP, NodeType.CONTROL}),
        EdgeType.COMMUNICATION: ({NodeType.STEP}, {NodeType.STEP}),
        EdgeType.CONTROL_FLOW: ({NodeType.CONTROL}, {NodeType.STEP, NodeType.CONTROL}),
        EdgeType.EXECUTION: ({NodeType.AGENT, NodeType.SKILL}, {NodeType.STEP}),
        EdgeType.WRITE: ({NodeType.STEP}, {NodeType.MEMORY}),
        EdgeType.READ: ({NodeType.MEMORY}, {NodeType.STEP}),
        EdgeType.SUPPORT: ({NodeType.EVIDENCE}, {NodeType.STEP}),
    }
    node_types = {node.node_id: node.node_type for node in blueprint.nodes}
    for edge in blueprint.edges:
        if edge.source_id not in node_types or edge.target_id not in node_types:
            raise ACGValidationError(
                f"ACG edge {edge.edge_id} references missing endpoint: "
                f"{edge.source_id} -> {edge.target_id}"
            )
        source_types, target_types = allowed[edge.edge_type]
        if node_types[edge.source_id] not in source_types or node_types[edge.target_id] not in target_types:
            raise ACGValidationError(
                f"ACG edge {edge.edge_id} has invalid endpoint types for {edge.edge_type.value}: "
                f"{node_types[edge.source_id].value} -> {node_types[edge.target_id].value}"
            )
        if edge.edge_type == EdgeType.DEPENDENCY and edge.source_id == edge.target_id:
            raise ACGValidationError(f"ACG dependency edge {edge.edge_id} cannot target itself")


def _validate_conditional_control(blueprint: ACGBlueprint, node: ControlNode) -> None:
    if node.condition_spec is None:
        raise ACGValidationError(f"IF control {node.node_id} requires conditionSpec")
    if not 2 <= len(node.branch_edge_ids) <= 4:
        raise ACGValidationError(f"IF control {node.node_id} requires 2..4 branch edges")
    if len(set(node.branch_edge_ids)) != len(node.branch_edge_ids):
        raise ACGValidationError(f"IF control {node.node_id} has duplicate branchEdgeIds")
    if not blueprint.has_node(node.condition_spec.source_node_id):
        raise ACGValidationError(f"IF source node missing: {node.condition_spec.source_node_id}")
    if node.join_node_id and not blueprint.has_node(node.join_node_id):
        raise ACGValidationError(f"IF join node missing: {node.join_node_id}")
    source_node = blueprint.get_node(node.condition_spec.source_node_id)
    if source_node.node_type != NodeType.STEP:
        raise ACGValidationError(f"IF source must be a Step: {source_node.node_id}")
    if node.join_node_id:
        join_node = blueprint.get_node(node.join_node_id)
        if not isinstance(join_node, ControlNode) or join_node.control_type in {
            ControlType.IF,
            ControlType.LOOP,
        }:
            raise ACGValidationError(f"IF join must be an unconditional Control: {node.join_node_id}")
    incoming = blueprint.incoming(node.node_id, EdgeType.DEPENDENCY)
    if len(incoming) != 1 or incoming[0].source_id != node.condition_spec.source_node_id:
        raise ACGValidationError(f"IF control {node.node_id} requires its single declared source")
    outgoing = [
        edge
        for edge in blueprint.outgoing(node.node_id)
        if edge.edge_type in {EdgeType.DEPENDENCY, EdgeType.CONTROL_FLOW}
    ]
    if {edge.edge_id for edge in outgoing} != set(node.branch_edge_ids):
        raise ACGValidationError(f"IF control {node.node_id} has undeclared branch edges")
    declared = set(node.branch_edge_ids)
    case_edges = set(node.condition_spec.cases.values())
    if not case_edges or not case_edges.issubset(declared):
        raise ACGValidationError(f"IF control {node.node_id} has invalid condition cases")
    if node.condition_spec.default_edge_id and node.condition_spec.default_edge_id not in declared:
        raise ACGValidationError(f"IF control {node.node_id} has invalid defaultEdgeId")
    selectable = case_edges | (
        {node.condition_spec.default_edge_id} if node.condition_spec.default_edge_id else set()
    )
    if selectable != declared:
        raise ACGValidationError(f"IF control {node.node_id} has an unreachable branch")
    if node.join_node_id:
        try:
            exclusive = conditional_branch_exclusive_nodes(blueprint, node)
        except ConditionEvaluationError as exc:
            raise ACGValidationError(f"{exc.code}: {exc}") from exc
        for node_ids in exclusive.values():
            for node_id in node_ids:
                branch_node = blueprint.get_node(node_id)
                if isinstance(branch_node, ControlNode) and branch_node.control_type in {
                    ControlType.IF,
                    ControlType.LOOP,
                }:
                    raise ACGValidationError(f"nested IF/LOOP is unsupported: {branch_node.node_id}")


def validate_blueprint(blueprint: ACGBlueprint) -> None:
    """规划器交付前的图级验证。非法则抛 ACGValidationError。"""
    step_nodes = blueprint.step_nodes()
    if not step_nodes:
        raise ACGValidationError("ACG must contain at least one Step node")

    node_ids = [node.node_id for node in blueprint.nodes]
    duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicate_nodes:
        raise ACGValidationError(f"ACG has duplicate node ids: {duplicate_nodes}")
    edge_ids = [edge.edge_id for edge in blueprint.edges]
    duplicate_edges = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    if duplicate_edges:
        raise ACGValidationError(f"ACG has duplicate edge ids: {duplicate_edges}")

    _validate_edge_endpoints(blueprint)
    cycle = detect_cycle(blueprint)
    if cycle:
        raise ACGValidationError(f"ACG contains a cycle: {' -> '.join(cycle)}")

    for node in blueprint.nodes:
        if isinstance(node, ControlNode) and node.control_type == ControlType.LOOP:
            if node.loop_spec is None:
                raise ACGValidationError(f"LOOP control {node.node_id} requires loopSpec")
            for ref in (node.loop_spec.body_entry_id, node.loop_spec.body_exit_id):
                if not blueprint.has_node(ref):
                    raise ACGValidationError(f"LOOP control {node.node_id} references missing node: {ref}")
        if isinstance(node, ControlNode) and node.control_type == ControlType.PARALLEL:
            if node.parallel_spec is not None:
                refs = [*node.parallel_spec.branch_entry_ids, node.parallel_spec.join_node_id]
                if len(set(node.parallel_spec.branch_entry_ids)) != len(node.parallel_spec.branch_entry_ids):
                    raise ACGValidationError(f"PARALLEL control {node.node_id} has duplicate branches")
                if any(not blueprint.has_node(ref) for ref in refs):
                    raise ACGValidationError(f"PARALLEL control {node.node_id} references missing nodes")
        if isinstance(node, ControlNode) and node.control_type == ControlType.CONSENSUS:
            if node.consensus_spec is not None:
                if node.consensus_spec.quorum > len(node.consensus_spec.participant_step_ids):
                    raise ACGValidationError(f"CONSENSUS control {node.node_id} quorum exceeds participants")
                if any(not blueprint.has_node(ref) for ref in node.consensus_spec.participant_step_ids):
                    raise ACGValidationError(f"CONSENSUS control {node.node_id} references missing participants")
        if isinstance(node, ControlNode) and node.control_type == ControlType.IF:
            _validate_conditional_control(blueprint, node)
        if not isinstance(node, StepNode):
            continue
        explicit_agent_binding = any(
            edge.edge_type is EdgeType.EXECUTION
            and edge.target_id == node.node_id
            and isinstance(blueprint.get_node(edge.source_id), AgentNode)
            for edge in blueprint.edges
        )
        if not node.agent_name and not explicit_agent_binding:
            raise ACGValidationError(
                f"Step node {node.node_id} requires AgentNode + EXECUTION or legacy agentName"
            )
        try:
            check_contract_schema(node.output_spec, label=f"{node.node_id}.outputSpec")
        except ValueError as exc:
            raise ACGValidationError(str(exc)) from exc
        input_schema = node.input_spec.get("schema") if isinstance(node.input_spec, dict) else None
        if isinstance(input_schema, dict):
            try:
                check_contract_schema(input_schema, label=f"{node.node_id}.inputSpec.schema")
            except ValueError as exc:
                raise ACGValidationError(str(exc)) from exc
        from_map = node.input_spec.get("from") if isinstance(node.input_spec, dict) else None
        if isinstance(from_map, dict):
            for source_id in from_map:
                source = str(source_id)
                if not blueprint.has_node(source):
                    raise ACGValidationError(f"Step {node.node_id} input.from references missing Step {source}")
                source_node = blueprint.get_node(source)
                if source_node.node_type != NodeType.STEP:
                    raise ACGValidationError(f"Step {node.node_id} input.from source is not a Step: {source}")
                if not _has_dependency_path(blueprint, source, node.node_id):
                    raise ACGValidationError(
                        f"Step {node.node_id} consumes {source} without an execution dependency path"
                    )

    for edge in blueprint.edges_of_type(EdgeType.COMMUNICATION):
        if not _has_dependency_path(blueprint, edge.source_id, edge.target_id):
            raise ACGValidationError(
                f"Communication edge {edge.edge_id} has no execution dependency path: "
                f"{edge.source_id} -> {edge.target_id}"
            )


def ready_steps(blueprint: ACGBlueprint, completed: Set[str]) -> List[str]:
    """计算就绪集：所有 DEPENDENCY 前驱都已完成、且自身未完成的 STEP 节点。

    这是执行器并行调度的核心：返回的全部 step 之间彼此无依赖，可并发执行。
    """
    ready: List[str] = []
    for step in blueprint.step_nodes():
        if step.node_id in completed:
            continue
        deps = blueprint.dependency_sources(step.node_id)
        if all(dep in completed for dep in deps):
            ready.append(step.node_id)
    return ready


"""线性工作流 → ACG 自动升格。

现有 WorkflowDefinition 是基于 nextStepId 的线性步骤链。本模块把它无损
升格为 ACGBlueprint：每个 step 变成一个 StepNode，相邻 step 之间连一条
DEPENDENCY 边。一条线性链就是一张最简单的 DAG，因此升格后的图可被
ACG 执行器以“就绪集调度”方式执行，行为与原线性执行完全一致。

这保证了存量工作流零改动接入新架构，是“静态优选、动态补位”里
“静态”一侧的落地基础。
"""


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any as WorkflowDefinition


def _complexity_from_step_count(count: int) -> ComplexityLevel:
    if count <= 3:
        return ComplexityLevel.SIMPLE
    if count <= 7:
        return ComplexityLevel.MEDIUM
    if count <= 15:
        return ComplexityLevel.COMPLEX
    return ComplexityLevel.EXTREME


# 注入认知节点的关键词规则（覆盖中英文 capability / stepId）：
# - 产生结论性内容、值得沉淀的步骤 → 注入 Memory 节点
# - 需要外部依据支撑、可审计的步骤 → 注入 Evidence 节点
_MEMORY_KEYWORDS = ("risk", "风险", "suggest", "revision", "建议", "report", "报告", "analysis", "分析", "summary", "结论")
_EVIDENCE_KEYWORDS = ("evidence", "证据", "依据", "statute", "法条", "citation")


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


def promote_workflow_to_acg(
    workflow: "WorkflowDefinition",
    *,
    mission_id: str | None = None,
    enrich: bool = True,
) -> ACGBlueprint:
    """把线性 WorkflowDefinition 升格为 ACGBlueprint。

    - 保留 step 顺序：用每个 step 的 stepId 作为 StepNode.node_id。
    - 依赖边：按 next_step_id 串联；若无显式 next，则按声明顺序串联。
    - reviewRequired 透传到 StepNode.review_required。
    - enrich=True（默认）时注入认知协作节点，使图从线性链变为多层认知网络：
        * 每个 Step 挂一个执行 Agent 节点（按 agentName 去重复用）+ EXECUTION 边
        * 产出结论的 Step 挂 Memory 节点 + WRITE 边
        * 需外部依据的 Step 挂 Evidence 节点 + SUPPORT 边
      这些节点与边不参与就绪集调度（执行器只看 STEP + DEPENDENCY），
      因此不改变执行行为，仅丰富拓扑的认知协作语义与可视化表达。
    """
    steps = list(workflow.steps)
    blueprint = ACGBlueprint(
        missionId=mission_id,
        objective=workflow.description or workflow.name,
        complexityLevel=_complexity_from_step_count(len(steps)),
        metadata={
            "sourceWorkflowId": workflow.workflow_id,
            "sourceWorkflowVersion": workflow.version,
            "promotedFromLinear": True,
            "enriched": enrich,
            "runtimeEngine": workflow.effective_runtime_engine,
        },
    )

    for definition in steps:
        node = StepNode(
            nodeId=definition.step_id,
            name=definition.name,
            stepType="agent",
            goal=definition.name,
            agentName=definition.agent_name,
            capability=definition.capability,
            inputSpec=dict(definition.input),
            outputSpec=dict(definition.output_spec),
            reviewRequired=definition.review_required,
            retryLimit=definition.max_retries,
            timeout=definition.timeout,
            priority=definition.priority,
        )
        blueprint.nodes.append(node)

    # 构建依赖边：优先用显式 next_step_id，回退到声明顺序。
    step_ids = {definition.step_id for definition in steps}
    for index, definition in enumerate(steps):
        target_id = definition.next_step_id
        if target_id in ("", "done", "completed", None):
            target_id = None
        if target_id is None and index + 1 < len(steps):
            target_id = steps[index + 1].step_id
        if target_id and target_id in step_ids:
            blueprint.edges.append(
                ACGEdge(
                    sourceId=definition.step_id,
                    targetId=target_id,
                    edgeType=EdgeType.DEPENDENCY,
                )
            )

    # input.from 是结构化通信契约。为每个声明的数据来源创建通信边，并补齐
    # 执行依赖，保证消费者不会在生产者完成前被调度。
    for definition in steps:
        from_map = definition.input.get("from") if isinstance(definition.input, dict) else None
        if not isinstance(from_map, dict):
            continue
        for source_id, fields in from_map.items():
            if source_id not in step_ids or source_id == definition.step_id:
                continue
            data_fields = [str(field) for field in fields] if isinstance(fields, list) else []
            blueprint.edges.append(
                ACGEdge(
                    sourceId=source_id,
                    targetId=definition.step_id,
                    edgeType=EdgeType.COMMUNICATION,
                    dataFields=data_fields,
                    metadata={"contract": "input.from"},
                )
            )
            if not any(
                edge.edge_type == EdgeType.DEPENDENCY
                and edge.source_id == source_id
                and edge.target_id == definition.step_id
                for edge in blueprint.edges
            ):
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=source_id,
                        targetId=definition.step_id,
                        edgeType=EdgeType.DEPENDENCY,
                        metadata={"derivedFrom": "input.from"},
                    )
                )

    if enrich:
        _inject_cognitive_nodes(blueprint, steps)

    blueprint.touch()
    return blueprint


def _inject_cognitive_nodes(blueprint: ACGBlueprint, steps) -> None:
    """为每个 Step 注入 Agent / Memory / Evidence 认知节点与关联边。"""
    agent_nodes: dict[str, str] = {}  # agentName -> agent_node_id（去重复用）
    memory_nodes: dict[str, str] = {}
    evidence_nodes: dict[str, str] = {}

    for definition in steps:
        step_id = definition.step_id
        agent_name = definition.agent_name or step_id
        cap = definition.capability or ""
        sig = f"{cap} {step_id}"

        # 1) 执行 Agent 节点（同名 Agent 复用一个节点，体现“一个 Agent 执行多个 Step”）
        if agent_name not in agent_nodes:
            an_id = f"agent::{agent_name}"
            blueprint.nodes.append(
                AgentNode(
                    nodeId=an_id,
                    name=agent_name,
                    role=cap or agent_name,
                    capabilityTags=[cap] if cap else [],
                )
            )
            agent_nodes[agent_name] = an_id
        blueprint.edges.append(
            ACGEdge(sourceId=agent_nodes[agent_name], targetId=step_id, edgeType=EdgeType.EXECUTION)
        )

        # 2) Evidence 节点（需外部依据支撑的步骤）
        output_properties = (
            definition.output_spec.get("properties", {})
            if isinstance(definition.output_spec, dict)
            else {}
        )
        declares_evidence_output = any(
            field in output_properties for field in ("evidence_refs", "evidenceRefs")
        )
        if declares_evidence_output or _matches(sig, _EVIDENCE_KEYWORDS):
            ev_id = _node_id("ev")
            blueprint.nodes.append(
                EvidenceNode(
                    nodeId=ev_id,
                    name=f"证据·{definition.name}",
                    evidenceType="retrieved",
                    producerStepId=step_id,
                    metadata={"producerStepId": step_id},
                )
            )
            evidence_nodes[step_id] = ev_id

        # 3) Memory 节点（产出结论、值得沉淀的步骤）
        memory_policy = (
            definition.input.get("memoryPolicy", {})
            if isinstance(definition.input, dict)
            else {}
        )
        declares_memory_write = (
            isinstance(memory_policy, dict) and memory_policy.get("write") is True
        )
        if declares_memory_write or _matches(sig, _MEMORY_KEYWORDS):
            memory_type = (
                str(memory_policy.get("writeType") or "episodic")
                if declares_memory_write
                else "episodic"
            )
            mem_id = _node_id("mem")
            blueprint.nodes.append(
                MemoryNode(nodeId=mem_id, name=f"记忆·{definition.name}", memoryType=memory_type)
            )
            blueprint.edges.append(
                ACGEdge(sourceId=step_id, targetId=mem_id, edgeType=EdgeType.WRITE)
            )
            memory_nodes[step_id] = mem_id

    # READ/SUPPORT 只连接真实声明消费该生产步骤的下游节点。
    for definition in steps:
        from_map = definition.input.get("from") if isinstance(definition.input, dict) else None
        if not isinstance(from_map, dict):
            continue
        for source_id in from_map:
            if source_id in memory_nodes:
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=memory_nodes[source_id],
                        targetId=definition.step_id,
                        edgeType=EdgeType.READ,
                    )
                )
            if source_id in evidence_nodes:
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=evidence_nodes[source_id],
                        targetId=definition.step_id,
                        edgeType=EdgeType.SUPPORT,
                    )
                )


"""Domain-neutral planning capability contracts and their validated catalog."""


from collections import OrderedDict
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field


PlanningRiskLevel = Literal["normal", "elevated", "high", "critical"]
_RISK_LEVEL_ORDER: tuple[PlanningRiskLevel, ...] = (
    "normal",
    "elevated",
    "high",
    "critical",
)


class CapabilityPromptProfile(BaseModel):
    """Versioned, domain-neutral instructions used to select and execute a capability."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    profile_id: str = Field(default="generic", alias="profileId")
    prompt_profile_version: str = Field(default="capability-profile.v1", alias="promptProfileVersion")
    purpose: str = ""
    when_to_use: list[str] = Field(default_factory=list, alias="whenToUse")
    when_not_to_use: list[str] = Field(default_factory=list, alias="whenNotToUse")
    decomposition_hints: list[str] = Field(default_factory=list, alias="decompositionHints")
    execution_principles: list[str] = Field(default_factory=list, alias="executionPrinciples")
    quality_criteria: list[str] = Field(default_factory=list, alias="qualityCriteria")
    verification_questions: list[str] = Field(default_factory=list, alias="verificationQuestions")
    required_tools: list[str] = Field(default_factory=list, alias="requiredTools")
    evidence_policy: str = Field(default="Use only supplied or tool-returned evidence.", alias="evidencePolicy")


class PlanningCapabilityDescriptor(BaseModel):
    """解析、路由和 ACG 构造共享的稳定能力描述。

    标识、别名、依赖和领域提示决定可发现性；输入/输出合同与产物、证据、内存、审核及风险
    标志决定图构造边界。插件来源字段将贡献锁定到版本化安装包。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    capability_id: str = Field(alias="capabilityId")
    display_name: str = Field(alias="displayName")
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    prompt_profile: CapabilityPromptProfile = Field(
        default_factory=CapabilityPromptProfile,
        alias="promptProfile",
    )
    planning_stage: str = Field(default="analysis", alias="planningStage")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    optional_dependencies: list[str] = Field(default_factory=list, alias="optionalDependencies")
    input_contract: dict = Field(default_factory=dict, alias="inputContract")
    output_contract: dict = Field(default_factory=dict, alias="outputContract")
    produces_artifact: bool = Field(default=False, alias="producesArtifact")
    requires_evidence: bool = Field(default=False, alias="requiresEvidence")
    writes_memory: bool = Field(default=False, alias="writesMemory")
    requires_review: bool = Field(default=False, alias="requiresReview")
    risk_level_hint: PlanningRiskLevel = Field(default="normal", alias="riskLevelHint")
    parallelizable: bool = True
    domain_hints: list[str] = Field(default_factory=list, alias="domainHints")
    priority: int = 100
    source: Literal["native", "plugin"] = "native"
    plugin_id: str | None = Field(default=None, alias="pluginId")
    plugin_version: str | None = Field(default=None, alias="pluginVersion")
    contribution_id: str | None = Field(default=None, alias="contributionId")


class CapabilityCatalog:
    """经校验且顺序确定的可执行规划能力注册表。"""

    def __init__(self, descriptors: Iterable[PlanningCapabilityDescriptor] = ()) -> None:
        self._descriptors: OrderedDict[str, PlanningCapabilityDescriptor] = OrderedDict()
        self._aliases: dict[str, str] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: PlanningCapabilityDescriptor) -> None:
        """注册一个能力描述符并规范化标识与别名。

        保持插入顺序；重复能力或与其他能力冲突的别名会抛出 ``ValueError``，失败前不写入。
        """
        capability_id = self._normalize(descriptor.capability_id)
        if not capability_id:
            raise ValueError("capabilityId is required")
        if capability_id in self._descriptors:
            raise ValueError(f"duplicate capabilityId: {descriptor.capability_id}")

        normalized = descriptor.model_copy(
            update={
                "capability_id": capability_id,
                "depends_on": [self._normalize(item) for item in descriptor.depends_on],
                "optional_dependencies": [
                    self._normalize(item) for item in descriptor.optional_dependencies
                ],
                "domain_hints": [self._normalize(item) for item in descriptor.domain_hints],
            }
        )
        alias_values = [capability_id, *normalized.aliases]
        for value in alias_values:
            alias = self._normalize(value)
            existing = self._aliases.get(alias)
            if existing is not None and existing != capability_id:
                raise ValueError(f"duplicate capability alias: {value}")

        self._descriptors[capability_id] = normalized
        for value in alias_values:
            self._aliases[self._normalize(value)] = capability_id

    def get(self, capability_id: str) -> PlanningCapabilityDescriptor:
        """按规范化能力标识获取描述符；未注册时抛出 ``KeyError``。"""
        normalized = self._normalize(capability_id)
        try:
            return self._descriptors[normalized]
        except KeyError as exc:
            raise KeyError(f"planning capability not registered: {capability_id}") from exc

    def resolve(self, value: str) -> PlanningCapabilityDescriptor:
        """按能力标识或别名解析描述符；别名冲突已在注册阶段禁止。"""
        normalized = self._normalize(value)
        capability_id = self._aliases.get(normalized)
        if capability_id is None:
            raise KeyError(f"planning capability not registered: {value}")
        return self._descriptors[capability_id]

    def available(self, domain_hint: str | None = None) -> tuple[PlanningCapabilityDescriptor, ...]:
        """返回领域可见描述符的不可变序列，按 ``(priority, capability_id)`` 稳定排序。"""
        domain = self._normalize(domain_hint or "")
        descriptors = [
            descriptor
            for descriptor in self._descriptors.values()
            if not domain
            or not descriptor.domain_hints
            or domain in descriptor.domain_hints
            or "general" in descriptor.domain_hints
        ]
        return tuple(sorted(descriptors, key=lambda item: (item.priority, item.capability_id)))

    def scoped(self, capability_ids: Iterable[str]) -> "CapabilityCatalog":
        """构建隔离能力目录视图，不修改全局目录；返回项深拷贝并重新校验依赖。"""

        allowed = {self._normalize(item) for item in capability_ids}
        scoped = CapabilityCatalog(
            descriptor.model_copy(deep=True)
            for capability_id, descriptor in self._descriptors.items()
            if capability_id in allowed
        )
        scoped.validate()
        return scoped

    def validate(self) -> None:
        """验证依赖均已注册且不存在环；深度优先遍历，复杂度 ``O(V+E)``。"""
        for descriptor in self._descriptors.values():
            for dependency in [*descriptor.depends_on, *descriptor.optional_dependencies]:
                if dependency not in self._descriptors:
                    raise ValueError(
                        f"capability {descriptor.capability_id} has dangling dependency: {dependency}"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in visiting:
                raise ValueError(f"capability dependency cycle detected at: {capability_id}")
            if capability_id in visited:
                return
            visiting.add(capability_id)
            descriptor = self._descriptors[capability_id]
            for dependency in [*descriptor.depends_on, *descriptor.optional_dependencies]:
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)

        for capability_id in self._descriptors:
            visit(capability_id)

    def expand_dependencies(self, capability_ids: Iterable[str]) -> list[str]:
        """展开必需依赖并返回依赖先于依赖者的去重顺序，复杂度 ``O(V+E)``。"""
        selected: list[str] = []
        visited: set[str] = set()

        def include(value: str) -> None:
            descriptor = self.resolve(value)
            if descriptor.capability_id in visited:
                return
            for dependency in descriptor.depends_on:
                include(dependency)
            visited.add(descriptor.capability_id)
            selected.append(descriptor.capability_id)

        for capability_id in capability_ids:
            include(capability_id)
        return selected

    @staticmethod
    def _normalize(value: str) -> str:
        return (value or "").strip().lower()


def highest_planning_risk_level(values: Iterable[str]) -> PlanningRiskLevel:
    """返回输入中已识别声明式规划风险的最高级别；未知值忽略，空集合回退 ``normal``。"""

    ranks = {value: index for index, value in enumerate(_RISK_LEVEL_ORDER)}
    normalized = [str(value or "").strip().lower() for value in values]
    return max(
        (value for value in normalized if value in ranks),
        key=ranks.__getitem__,
        default="normal",
    )


"""Build the Core-owned Native capability catalog."""

# 同文件定义的目录与默认注册函数在运行时按名称解析，无需跨包导入。


def build_default_capability_catalog() -> CapabilityCatalog:
    """创建并校验内置能力目录；每次调用返回独立实例，不共享可变注册状态。"""
    catalog = CapabilityCatalog()
    register_native_capabilities(catalog)
    catalog.validate()
    return catalog


"""Core-owned, bounded capability contribution for native domain-neutral tasks."""


# 同文件定义的能力描述合同在运行时按名称解析。


def _schema(*required: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {} for name in required},
        "required": list(required),
    }


def _record(properties: dict, *required: str) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
    }


def _records(properties: dict, *required: str, max_items: int | None = None) -> dict:
    schema = {
        "type": "array",
        "items": _record(properties, *required),
    }
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


_TEXT = {"type": "string"}
_DELIVERABLE_TEXT = {"type": "string", "minLength": 1}


def _text_list(*, max_items: int | None = None, max_length: int | None = None) -> dict:
    item_schema: dict[str, object] = {"type": "string"}
    if max_length is not None:
        item_schema["maxLength"] = max_length
    schema: dict[str, object] = {
        "type": "array",
        "items": item_schema,
    }
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


_TEXT_LIST = _text_list()


def _output_schema(capability_id: str) -> dict:
    schemas = {
        "task_understanding": _record(
            {
                "task_summary": _TEXT,
                "constraints": _records(
                    {"constraint": _TEXT, "source": _TEXT, "mandatory": {"type": "boolean"}},
                    "constraint",
                    "source",
                    "mandatory",
                ),
                "success_criteria": _text_list(),
                "assumptions": _TEXT_LIST,
                "open_questions": _TEXT_LIST,
            },
            "task_summary",
            "constraints",
        ),
        "information_extraction": _record(
            {
                "extracted_information": _record(
                    {
                        "facts": _records(
                            {"name": _TEXT, "value": {}, "source": _TEXT},
                            "name",
                            "value",
                            "source",
                        ),
                        "metrics": _records(
                            {"name": _TEXT, "value": {}, "unit": _TEXT, "source": _TEXT},
                            "name",
                            "value",
                            "unit",
                            "source",
                        ),
                        "entities": _TEXT_LIST,
                        "unknowns": _TEXT_LIST,
                    },
                    "facts",
                    "metrics",
                    "entities",
                    "unknowns",
                )
            },
            "extracted_information",
        ),
        "information_retrieval": _record(
            {
                "retrieved_information": _TEXT_LIST,
                "evidence_refs": _TEXT_LIST,
                "sources": {"type": "array", "items": {"type": "object"}},
                "retrieval_mode": _TEXT,
            },
            "retrieved_information",
            "evidence_refs",
        ),
        "requirement_analysis": _record(
            {
                "requirements": _records(
                    {"id": _TEXT, "requirement": _TEXT, "priority": _TEXT, "source": _TEXT},
                    "id",
                    "requirement",
                    "priority",
                    "source",
                ),
                "acceptance_criteria": _records(
                    {"requirement_id": _TEXT, "criterion": _TEXT, "metric": _TEXT, "target": _TEXT},
                    "requirement_id",
                    "criterion",
                    "metric",
                    "target",
                ),
                "assumptions": _TEXT_LIST,
                "open_questions": _TEXT_LIST,
            },
            "requirements",
            "acceptance_criteria",
        ),
        "process_decomposition": _record(
            {
                "process_steps": _records(
                    {
                        "id": _TEXT,
                        "name": _TEXT,
                        "inputs": _TEXT_LIST,
                        "activities": _TEXT_LIST,
                        "outputs": _TEXT_LIST,
                        "owner": _TEXT,
                        "quality_gate": _TEXT,
                    },
                    "id",
                    "name",
                    "inputs",
                    "activities",
                    "outputs",
                    "owner",
                    "quality_gate",
                )
            },
            "process_steps",
        ),
        "resource_planning": _record(
            {
                "resource_plan": _record(
                    {"people": _TEXT_LIST, "equipment": _TEXT_LIST, "systems": _TEXT_LIST, "materials": _TEXT_LIST},
                    "people",
                    "equipment",
                    "systems",
                    "materials",
                ),
                "capacity_plan": _record(
                    {"assumptions": _TEXT_LIST, "calculations": _TEXT_LIST, "conclusion": _TEXT},
                    "assumptions",
                    "calculations",
                    "conclusion",
                ),
            },
            "resource_plan",
            "capacity_plan",
        ),
        "architecture_design": _record(
            {
                "architecture": _record({"style": _TEXT, "rationale": _TEXT, "deployment": _TEXT}, "style", "rationale", "deployment"),
                "components": _records({"name": _TEXT, "responsibility": _TEXT, "interfaces": _TEXT_LIST}, "name", "responsibility", "interfaces"),
                "data_flow": _records({"source": _TEXT, "target": _TEXT, "data": _TEXT, "controls": _TEXT_LIST}, "source", "target", "data", "controls"),
            },
            "architecture",
            "components",
            "data_flow",
        ),
        "analysis": _record(
            {
                "analysis": _record(
                    {
                        "findings": _text_list(),
                        "assumptions": {
                            **_text_list(),
                            "default": [],
                        },
                        "gaps": {
                            **_text_list(),
                            "default": [],
                        },
                    },
                    "findings",
                    "assumptions",
                    "gaps",
                )
            },
            "analysis",
        ),
        "evidence_analysis": _record(
            {"evidence_analysis": _records({"claim": _TEXT, "evidence_ref": _TEXT, "assessment": _TEXT, "confidence": {"type": "number"}}, "claim", "evidence_ref", "assessment", "confidence"), "evidence_refs": _TEXT_LIST},
            "evidence_analysis",
            "evidence_refs",
        ),
        "comparative_analysis": _record(
            {"comparison": _record({"criteria": _TEXT_LIST, "scores": {"type": "array", "items": {"type": "object"}}, "recommendation": _TEXT}, "criteria", "scores", "recommendation"), "alternatives": _records({"name": _TEXT, "advantages": _TEXT_LIST, "disadvantages": _TEXT_LIST}, "name", "advantages", "disadvantages")},
            "comparison",
            "alternatives",
        ),
        "cost_analysis": _record(
            {"cost_analysis": _record({"currency": _TEXT, "items": _records({"item": _TEXT, "amount": {"type": "number"}, "basis": _TEXT}, "item", "amount", "basis"), "total": {"type": "number"}, "assumptions": _TEXT_LIST}, "currency", "items", "total", "assumptions"), "cost_drivers": _TEXT_LIST},
            "cost_analysis",
            "cost_drivers",
        ),
        "risk_analysis": _record(
            {"risk_analysis": _record({"summary": _TEXT, "overall_level": _TEXT}, "summary", "overall_level"), "risks": _records({"risk": _TEXT, "probability": _TEXT, "impact": _TEXT, "trigger": _TEXT, "owner": _TEXT, "mitigation": _TEXT}, "risk", "probability", "impact", "trigger", "owner", "mitigation")},
            "risk_analysis",
            "risks",
        ),
        "solution_design": _record(
            {"solution_design": _record({"overview": _TEXT, "phases": _records({"name": _TEXT, "milestones": _TEXT_LIST, "dependencies": _TEXT_LIST, "deliverables": _TEXT_LIST}, "name", "milestones", "dependencies", "deliverables")}, "overview", "phases")},
            "solution_design",
        ),
        "verification": _record(
            {"verification": _record({"status": {"type": "string", "enum": ["passed", "partial", "failed"]}, "checks": _records({"criterion": _TEXT, "result": _TEXT, "evidence": _TEXT}, "criterion", "result", "evidence"), "unresolved_gaps": _TEXT_LIST}, "status", "checks", "unresolved_gaps")},
            "verification",
        ),
        "artifact_generation": _record(
            {
                "deliverable": _record(
                    {
                        "title": _TEXT,
                        "executiveSummary": _TEXT,
                        "sections": _records(
                            {"title": _TEXT, "content": _TEXT, "sourceFields": _TEXT_LIST},
                            "title",
                            "content",
                            "sourceFields",
                        ),
                        "calculations": _records(
                            {"name": _TEXT, "formula": _TEXT, "inputs": _TEXT_LIST, "result": _TEXT, "assumptions": _TEXT_LIST},
                            "name",
                            "formula",
                            "inputs",
                            "result",
                            "assumptions",
                        ),
                        "assumptions": _TEXT_LIST,
                        "openQuestions": _TEXT_LIST,
                        "sourceRefs": _TEXT_LIST,
                    },
                    "title",
                    "executiveSummary",
                    "sections",
                    "calculations",
                    "assumptions",
                    "openQuestions",
                    "sourceRefs",
                ),
                "final_answer": _DELIVERABLE_TEXT,
                "verification": _record(
                    {
                        "status": {"type": "string", "enum": ["passed", "partial", "failed"]},
                        "checks": _records(
                            {"criterion": _TEXT, "result": _TEXT, "evidence": _TEXT},
                            "criterion",
                            "result",
                            "evidence",
                        ),
                        "unresolvedGaps": _TEXT_LIST,
                    },
                    "status",
                    "checks",
                    "unresolvedGaps",
                ),
                "artifact": _record(
                    {"artifactId": _TEXT, "artifactKey": _TEXT, "type": {"type": "string", "enum": ["report"]}, "title": _TEXT, "mediaType": {"type": "string", "enum": ["text/markdown"]}, "content": _DELIVERABLE_TEXT, "structuredData": {"type": "object"}, "manifestId": _TEXT, "checksum": _TEXT},
                    "artifactId",
                    "type",
                    "title",
                    "mediaType",
                    "content",
                    "structuredData",
                ),
                "artifacts": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "deliverable",
            "final_answer",
            "verification",
            "artifact",
        ),
    }
    return schemas[capability_id]


def native_capability_descriptors() -> tuple[PlanningCapabilityDescriptor, ...]:
    """返回内置通用能力描述符的有序不可变集合，供目录初始化或测试比较。"""
    general = ["general"]
    descriptors = (
        PlanningCapabilityDescriptor(
            capabilityId="task_understanding", displayName="任务理解",
            aliases=["理解任务", "任务目标", "目标", "约束"], planningStage="understand",
            outputContract=_output_schema("task_understanding"), parallelizable=False,
            domainHints=general, priority=10,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="information_extraction", displayName="信息提取",
            aliases=["信息提取", "抽取", "要素梳理"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("information_extraction"), domainHints=general, priority=20,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="information_retrieval", displayName="资料检索",
            aliases=["资料梳理", "资料检索", "信息检索", "调研", "文献"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("information_retrieval"),
            requiresEvidence=True, domainHints=general, priority=21,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="requirement_analysis", displayName="需求分析",
            aliases=["需求", "需求分析", "验收条件", "功能要求"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("requirement_analysis"),
            writesMemory=True, domainHints=general, priority=22,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="process_decomposition", displayName="流程拆解",
            aliases=["工序", "流程拆解", "流程规划", "步骤拆解", "生产流程"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("process_decomposition"), writesMemory=True,
            domainHints=general, priority=23,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="resource_planning", displayName="资源规划",
            aliases=["资源", "设备资源", "人员配置", "产能"], planningStage="analyze",
            dependsOn=["process_decomposition"], inputContract=_schema("process_steps"),
            outputContract=_output_schema("resource_planning"),
            domainHints=general, priority=30,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="architecture_design", displayName="架构设计",
            aliases=["系统架构", "技术架构", "架构设计", "组件", "接口", "数据流"],
            planningStage="analyze", dependsOn=["requirement_analysis"],
            inputContract=_schema("requirements"),
            outputContract=_output_schema("architecture_design"),
            writesMemory=True, domainHints=general, priority=31,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="analysis", displayName="通用分析",
            aliases=["分析", "评估"], planningStage="analyze",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("analysis"), domainHints=general, priority=32,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="evidence_analysis", displayName="证据分析",
            aliases=["证据分析", "依据分析", "资料分析"], planningStage="analyze",
            dependsOn=["information_retrieval"], inputContract=_schema("retrieved_information"),
            outputContract=_output_schema("evidence_analysis"),
            requiresEvidence=True, writesMemory=True, domainHints=general, priority=33,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="comparative_analysis", displayName="比较分析",
            aliases=["方案比较", "对比分析", "比较", "备选方案"], planningStage="analyze",
            dependsOn=["evidence_analysis"], inputContract=_schema("evidence_analysis"),
            outputContract=_output_schema("comparative_analysis"),
            domainHints=general, priority=34,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="cost_analysis", displayName="成本分析",
            aliases=["成本", "预算", "费用"], planningStage="analyze",
            dependsOn=["process_decomposition"], inputContract=_schema("process_steps"),
            outputContract=_output_schema("cost_analysis"),
            domainHints=general, priority=35,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="risk_analysis", displayName="风险分析",
            aliases=["风险", "安全风险", "风险分析", "风险控制"], planningStage="analyze",
            dependsOn=["task_understanding"],
            optionalDependencies=["requirement_analysis", "process_decomposition", "architecture_design"],
            inputContract=_schema("task_summary"), outputContract=_output_schema("risk_analysis"),
            writesMemory=True, riskLevelHint="high", domainHints=general, priority=36,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="solution_design", displayName="方案设计",
            aliases=["解决方案", "方案设计", "实施方案"], planningStage="synthesize",
            dependsOn=["analysis"], optionalDependencies=["requirement_analysis", "process_decomposition", "architecture_design"],
            inputContract=_schema("analysis"), outputContract=_output_schema("solution_design"),
            producesArtifact=True, writesMemory=True, domainHints=general, priority=40,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="verification", displayName="验证",
            aliases=["验证", "验收", "质量控制", "结论验证", "测试方式"], planningStage="verify",
            dependsOn=["task_understanding"],
            optionalDependencies=["requirement_analysis", "process_decomposition", "resource_planning", "architecture_design", "analysis", "comparative_analysis", "evidence_analysis", "cost_analysis", "risk_analysis", "solution_design"],
            inputContract=_schema("task_summary"), outputContract=_output_schema("verification"),
            parallelizable=False, domainHints=general, priority=50,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="artifact_generation", displayName="成果生成",
            aliases=["报告", "方案", "交付物", "文档"], planningStage="deliver",
            dependsOn=["task_understanding"],
            optionalDependencies=["information_extraction", "information_retrieval", "requirement_analysis", "process_decomposition", "resource_planning", "architecture_design", "analysis", "comparative_analysis", "evidence_analysis", "cost_analysis", "risk_analysis", "solution_design", "verification"],
            inputContract=_schema("task_summary"),
            outputContract=_output_schema("artifact_generation"),
            producesArtifact=True, writesMemory=True, parallelizable=False,
            domainHints=general, priority=60,
        ),
    )
    purposes = {
        "task_understanding": "Turn the mission into explicit goals, constraints, artifacts, facts, assumptions and unknowns.",
        "information_extraction": "Extract traceable facts, entities and metrics from supplied materials without adding facts.",
        "information_retrieval": "Retrieve missing information with source references and an explicit evidence boundary.",
        "requirement_analysis": "Translate stakeholder needs and hard constraints into testable requirements and acceptance criteria.",
        "process_decomposition": "Describe an executable process with inputs, outputs, ownership, dependencies and quality gates.",
        "resource_planning": "Estimate people, systems, equipment and capacity with assumptions and calculations.",
        "architecture_design": "Define components, interfaces, deployment boundaries and controlled data flows.",
        "analysis": "Analyze a bounded question and separate findings, assumptions and unresolved gaps.",
        "evidence_analysis": "Assess claims against cited evidence and state confidence and evidence gaps.",
        "comparative_analysis": "Compare independently produced alternatives against consistent criteria and explain the recommendation.",
        "cost_analysis": "Calculate costs from explicit quantities, rates, units, formulas and assumptions.",
        "risk_analysis": "Identify risks, triggers, probability, impact, ownership and mitigations.",
        "solution_design": "Design one coherent candidate solution with phases, dependencies, milestones and deliverables.",
        "verification": "Verify acceptance criteria against evidence; never pass a criterion without supporting evidence.",
        "artifact_generation": "Synthesize verified outputs into the requested artifacts while preserving gaps and source references.",
    }
    return tuple(
        descriptor.model_copy(update={
            "description": purposes[descriptor.capability_id],
            "prompt_profile": CapabilityPromptProfile(
                profileId=descriptor.capability_id,
                promptProfileVersion="capability-profile.v2",
                purpose=purposes[descriptor.capability_id],
                whenToUse=[f"The planned task primarily needs {descriptor.display_name}."],
                whenNotToUse=["Another capability owns the primary output; use this only for a distinct task."],
                decompositionHints=["Create separate instances when alternatives, stages or independently verifiable outputs differ."],
                executionPrinciples=[
                    "Use only mission facts, allowlisted context and tool-returned evidence.",
                    "Separate known facts, derivations, assumptions and unknowns.",
                ],
                qualityCriteria=[
                    "The output directly satisfies the planned task goal and every acceptance criterion.",
                    "Claims and calculations remain traceable to inputs, evidence or declared assumptions.",
                ],
                verificationQuestions=[
                    "Is every acceptance criterion answered?",
                    "Are unsupported claims marked as assumptions or unknowns?",
                ],
                requiredTools=(
                    ["knowledge_search"]
                    if descriptor.capability_id == "information_retrieval"
                    else []
                ),
                evidencePolicy=(
                    "A passed result requires a non-empty evidence reference for every check."
                    if descriptor.capability_id == "verification"
                    else "Use only supplied or tool-returned evidence and cite it when making a factual claim."
                ),
            ),
        })
        for descriptor in descriptors
    )


NATIVE_CAPABILITY_IDS = tuple(
    descriptor.capability_id for descriptor in native_capability_descriptors()
)


def register_native_capabilities(catalog: CapabilityCatalog) -> None:
    """按内置声明顺序注册能力到给定目录；直接修改该目录并沿用其冲突校验。"""
    for descriptor in native_capability_descriptors():
        catalog.register(descriptor)


"""任务语义画像。

意图解析模块的产物，是后续认知路由与 ACG 构建的统一输入。
"""


from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field

class CapabilityCandidate(BaseModel):
    """按目录归一且携带可审计置信分数的语义能力候选。

    ``score`` 被限制在 0 至 1，``matched_terms`` 和 ``source`` 保存推断依据；模型冻结，
    防止解析后的候选在路由前发生漂移。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    capability_id: str = Field(alias="capabilityId")
    score: float = Field(ge=0, le=1)
    matched_terms: List[str] = Field(default_factory=list, alias="matchedTerms")
    source: Literal["catalog_alias", "llm", "fallback", "dependency", "workflow_template"]
    rationale: str = ""


class ComplexityAssessment(BaseModel):
    """Deterministic six-axis complexity assessment used as a planning budget."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    level: ComplexityLevel
    score: int = Field(ge=0, le=18)
    dimensions: Dict[str, int] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    method: str = "deterministic-six-axis.v1"


class TaskSemanticProfile(BaseModel):
    """结构化任务语义画像。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    primary_goal: str = Field(default="", alias="primaryGoal")
    key_constraints: List[str] = Field(default_factory=list, alias="keyConstraints")
    required_capabilities: List[str] = Field(default_factory=list, alias="requiredCapabilities")
    capability_candidates: List[CapabilityCandidate] = Field(
        default_factory=list, alias="capabilityCandidates"
    )
    expected_artifacts: List[str] = Field(default_factory=list, alias="expectedArtifacts")
    verification_requirements: List[str] = Field(
        default_factory=list,
        alias="verificationRequirements",
    )
    estimated_complexity: ComplexityLevel = Field(
        default=ComplexityLevel.SIMPLE, alias="estimatedComplexity"
    )
    complexity_assessment: ComplexityAssessment | None = Field(
        default=None,
        alias="complexityAssessment",
    )
    domain_hint: str = Field(default="general", alias="domainHint")
    task_type_hint: str = Field(default="general", alias="taskTypeHint")
    implicit_requirements: List[str] = Field(default_factory=list, alias="implicitRequirements")
    risk_level: str = Field(default="normal", alias="riskLevel")
    resource_budget: Dict[str, Any] = Field(default_factory=dict, alias="resourceBudget")
    entropy_budget: int = Field(default=0, alias="entropyBudget")
    raw_intent: str = Field(default="", alias="rawIntent")

    def to_summary(self) -> str:
        """生成紧凑可读的画像摘要；能力按原列表顺序连接，不包含完整合同内容。"""
        caps = ", ".join(self.required_capabilities) or "(none)"
        return f"[{self.domain_hint}/{self.task_type_hint}] {self.primary_goal} | caps={caps}"


__all__ = [
    "ACGBlueprint", "RuntimeBlueprintSpec", "ACGEdge", "ACGNode", "ACGNodeBase", "ACGValidationError",
    "AgentNode", "BlueprintStatus", "CapabilityCandidate", "CapabilityCatalog",
    "CapabilityPromptProfile", "ComplexityAssessment",
    "ComplexityLevel", "ConditionEvaluationError", "ConditionOperator", "ConditionSpec",
    "ControlNode", "ControlType", "EdgeActivation", "EdgeType", "EvidenceNode",
    "MemoryNode", "NATIVE_CAPABILITY_IDS", "NodeType", "PlanningCapabilityDescriptor",
    "PlanningRiskLevel", "SkillNode", "StepNode", "TaskSemanticProfile",
    "build_default_capability_catalog", "detect_cycle", "find_dangling_dependencies",
    "highest_planning_risk_level", "native_capability_descriptors", "parse_node",
    "promote_workflow_to_acg", "ready_steps", "register_native_capabilities",
    "topological_order", "validate_blueprint",
]
