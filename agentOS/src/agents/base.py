"""AgentOS Core 的智能体基础接口，定义 AgentProfile、AgentOutput、运行上下文和 BaseAgent。"""


from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from contracts.workflow import AgentTask, WorkflowDefinition, WorkflowRun, WorkflowStep


class AgentProfile(BaseModel):
    """运行时配套的智能体注册描述，而非跨部件业务实现。

    名称、领域和能力决定解析候选；允许的技能/工具及风险级别限定调用边界，插件来源字段
    将实例绑定到安装包贡献版本。
    """
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
    """智能体一次调用的可序列化输出。

    ``output`` 为主结果，摘要、风险、来源、工具执行、证据和模型调用记录为审计辅助信息；
    模型允许未知字段以兼容插件演进。
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    output: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    risk_level: Optional[str] = Field(default=None, alias="riskLevel")
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    tool_executions: List[Dict[str, Any]] = Field(default_factory=list, alias="toolExecutions")
    evidence_refs: List[str] = Field(default_factory=list, alias="evidenceRefs")
    model_invocations: List[Dict[str, Any]] = Field(
        default_factory=list, alias="modelInvocations"
    )


class AgentRunContext(BaseModel):
    """传给智能体的单步运行上下文。

    任务、运行、工作流和步骤是本次调用的事实快照；内存及工具/模型运行时为注入依赖，
    调用方负责其生命周期与并发安全。
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: AgentTask
    run: WorkflowRun
    workflow: WorkflowDefinition
    step: WorkflowStep
    memory: Any
    context_pack: Optional[Any] = Field(default=None, alias="contextPack")
    tool_runtime: Optional[Any] = Field(default=None, alias="toolRuntime")
    model_runtime: Optional[Any] = Field(default=None, alias="modelRuntime")
    capability_descriptor: Optional[Any] = Field(
        default=None, alias="capabilityDescriptor"
    )


class BaseAgent(ABC):
    """所有应用层 Pack 智能体的统一接口。"""

    def __init__(self, profile: AgentProfile):
        self.profile = profile

    @abstractmethod
    async def run(self, context: AgentRunContext) -> AgentOutput:
        """执行当前步骤并返回结构化输出；实现应只通过 ``context`` 的注入依赖产生副作用。"""
        raise NotImplementedError

    async def review(self, context: AgentRunContext) -> AgentOutput:
        """审核步骤输出；默认复用 ``run``，专用智能体可覆盖为无副作用的审核逻辑。"""
        return await self.run(context)
