"""Agent 运行服务的基础模型与调用接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from contracts.workflow import AgentTask, WorkflowDefinition, WorkflowRun, WorkflowStep


class AgentProfile(BaseModel):
    """Agent 的注册描述，定义领域、能力、权限与插件来源。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    agent_name: str = Field(alias="agentName")
    domain: str
    capabilities: List[str] = Field(default_factory=list)
    allowed_skills: List[str] = Field(default_factory=list, alias="allowedSkills")
    allowed_tools: List[str] = Field(default_factory=list, alias="allowedTools")
    risk_level: str = Field(default="normal", alias="riskLevel")
    description: str = ""
    agent_id: Optional[str] = Field(default=None, alias="agentId")
    model_name: Optional[str] = Field(default=None, alias="modelName")
    binding_priority: int = Field(default=0, alias="bindingPriority")
    enabled: bool = True
    source: Literal["native", "plugin"] = "native"
    plugin_id: Optional[str] = Field(default=None, alias="pluginId")
    plugin_version: Optional[str] = Field(default=None, alias="pluginVersion")
    contribution_id: Optional[str] = Field(default=None, alias="contributionId")


class AgentOutput(BaseModel):
    """Agent 的结构化调用结果；运行时仅将其受控字段写入执行值仓库。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    output: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    risk_level: Optional[str] = Field(default=None, alias="riskLevel")
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    tool_executions: List[Dict[str, Any]] = Field(default_factory=list, alias="toolExecutions")
    evidence_refs: List[str] = Field(default_factory=list, alias="evidenceRefs")
    model_invocations: List[Dict[str, Any]] = Field(default_factory=list, alias="modelInvocations")


class AgentRunContext(BaseModel):
    """单个 ACG 节点传给 Agent 的受控上下文。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: AgentTask
    run: WorkflowRun
    workflow: WorkflowDefinition
    step: WorkflowStep
    memory: Any
    context_pack: Optional[Any] = Field(default=None, alias="contextPack")
    tool_runtime: Optional[Any] = Field(default=None, alias="toolRuntime")
    model_runtime: Optional[Any] = Field(default=None, alias="modelRuntime")
    capability_descriptor: Optional[Any] = Field(default=None, alias="capabilityDescriptor")


class BaseAgent(ABC):
    """应用层 Agent 的统一异步接口。"""

    def __init__(self, profile: AgentProfile):
        self.profile = profile

    @abstractmethod
    async def run(self, context: AgentRunContext) -> AgentOutput:
        """执行一个已经完成合同装配的节点，并返回结构化产物。"""
        raise NotImplementedError

    async def review(self, context: AgentRunContext) -> AgentOutput:
        """默认审核行为复用正常执行；专用审核 Agent 可以覆盖。"""
        return await self.run(context)
