"""Agent Profile 到已注册模型的 ACG 绑定测试。"""

from __future__ import annotations

import asyncio

from adapters.model_compatibility import ModelCompatibilityRegistry
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
    ModelInvocationResponse,
)
from contracts.workflow import WorkflowDefinition, WorkflowStatus, WorkflowStepDefinition
from components.mission_manager.store import WorkflowRegistry
from runtime.workflow_runtime import ExecutionRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _ProfileProvider:
    """记录经 Profile 选择的模型请求。"""

    def __init__(self) -> None:
        self.commit_ids: list[str | None] = []

    @property
    def manifest(self) -> CapabilityManifest:
        """声明测试 Agent 所选的唯一模型。"""
        return CapabilityManifest(
            capabilityId="model.profile.local",
            kind=CapabilityKind.MODEL,
            displayName="Profile local",
            provider="openai_compatible",
            capabilities=["profile-chat"],
        )

    def is_available(self) -> bool:
        """该测试提供商始终健康。"""
        return True

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResponse:
        """返回 Agent 输出合同需要的字段。"""
        self.commit_ids.append(request.commit_id)
        return ModelInvocationResponse(
            requestId=request.request_id,
            content={"answer": "selected"},
            provider="openai_compatible",
            model=request.model,
        )


class _ProfileAgent(BaseAgent):
    """只依赖节点上下文模型运行时的最小 Agent。"""

    async def run(self, context) -> AgentOutput:
        """调用当前节点被绑定的模型，不使用全局模型运行时。"""
        result = await context.model_runtime.generate_json(
            prompt="return json",
            schema={"type": "object", "properties": {"answer": {"type": "string"}}},
            commit_id=context.commit_id,
        )
        return AgentOutput(output=result.data)


def test_runtime_selects_registered_model_from_agent_profile() -> None:
    """Profile 的 modelProvider 与 modelName 必须决定节点模型，而非使用全局默认值。"""
    provider = _ProfileProvider()
    model_registry = ModelCompatibilityRegistry()
    model_registry.register(provider)
    agents = AgentRegistry()
    agent = _ProfileAgent(
        AgentProfile(
            agentName="profile-agent",
            domain="general",
            modelProvider="openai_compatible",
            modelName="profile-chat",
        )
    )
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="profile-model",
            name="profile model",
            domain="general",
            runtimeEngine="acg",
            steps=[
                WorkflowStepDefinition(
                    stepId="one",
                    name="one",
                    agentName="profile-agent",
                    outputSpec={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                    },
                )
            ],
        )
    )
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        model_registry=model_registry,
    )
    task = runtime.create_mission("profile", workflow_id="profile-model")
    _, run = runtime.prepare_run(task.mission_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert provider.commit_ids == [f"commit:{run.run_id}:one:0"]
