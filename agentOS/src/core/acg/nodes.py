"""
    ACG 节点定义
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from core.acg.enums import BlueprintStatus, ControlType, NodeType
from core.conditions import ConditionSpec


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
        return self.node_id

    @computed_field(alias="stepName", return_type=str)
    @property
    def step_name(self) -> str:
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
        return self.node_id

    @computed_field(alias="agentName", return_type=str)
    @property
    def agent_name(self) -> str:
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
        return self.node_id

    @computed_field(alias="skillName", return_type=str)
    @property
    def skill_name(self) -> str:
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
        return self.node_id

    @computed_field(alias="memoryName", return_type=str)
    @property
    def memory_name(self) -> str:
        return self.name


class EvidenceNode(ACGNodeBase):
    """证据节点 承载可信交付与审计依据。"""

    node_type: Literal[NodeType.EVIDENCE] = Field(default=NodeType.EVIDENCE, alias="nodeType")
    evidence_type: str = Field(default="document", alias="evidenceType")
    source: str = ""
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")

    @computed_field(alias="evidenceId", return_type=str)
    @property
    def evidence_id(self) -> str:
        return self.node_id

    @computed_field(alias="evidenceName", return_type=str)
    @property
    def evidence_name(self) -> str:
        return self.name


class ControlNode(ACGNodeBase):
    """控制节点 实现条件/循环/并行/共识。"""

    node_type: Literal[NodeType.CONTROL] = Field(default=NodeType.CONTROL, alias="nodeType")
    control_type: ControlType = Field(default=ControlType.START, alias="controlType")
    condition: str = ""
    condition_spec: Optional[ConditionSpec] = Field(default=None, alias="conditionSpec")
    branch_edge_ids: List[str] = Field(default_factory=list, alias="branchEdgeIds")
    join_node_id: Optional[str] = Field(default=None, alias="joinNodeId")

    @computed_field(alias="controlId", return_type=str)
    @property
    def control_id(self) -> str:
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


__all__ = [
    "ACGNodeBase",
    "StepNode",
    "AgentNode",
    "SkillNode",
    "MemoryNode",
    "EvidenceNode",
    "ControlNode",
    "ACGNode",
    "parse_node",
    "_node_id",
]
