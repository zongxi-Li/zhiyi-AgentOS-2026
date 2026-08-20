"""统一资源目录与 ACG 冻结 Agent 绑定的运行时测试。"""

from __future__ import annotations

import asyncio

from components.task_manager.store import WorkflowRegistry
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from runtime.workflow_runtime import WorkflowRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _BoundAgent(BaseAgent):
    """记录调用身份，用于证明执行期没有重新做全局 Agent 选择。"""

    def __init__(self, profile: AgentProfile, calls: list[str]) -> None:
        super().__init__(profile)
        self.calls = calls

    async def run(self, context):
        self.calls.append(str(self.profile.agent_id))
        return AgentOutput(output={"agent": self.profile.agent_id})


def _runtime(calls: list[str]) -> tuple[WorkflowRuntime, AgentRegistry]:
    """建立一个按 capability 解析 Agent 的最小 ACG Runtime。"""
    agents = AgentRegistry()
    agents.register(_BoundAgent(AgentProfile(
        agentId="agent-primary", agentName="primary", domain="general",
        capabilities=["analysis"], bindingPriority=1,
    ), calls))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="resource-run", name="resource", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="analyse", name="analyse", agentName="", capability="analysis")],
    ))
    return WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    ), agents


def test_prepare_run_freezes_resource_bindings() -> None:
    """每个 ACG Step 必须在准备期固定对应的 agentId。"""
    runtime, _ = _runtime([])
    task = runtime.create_task("resource", workflow_id="resource-run")

    _, run = runtime.prepare_run(task.task_id)

    assert run.execution_state["resourceBindings"] == {"analyse": "agent-primary"}
    assert run.execution_state["bindingRequirements"] == {
        "analyse": {
            "requiredCapabilities": ["analysis"],
            "domain": "general",
            "resourceTypes": ["agent"],
            "allowedResourceIds": ["agent-primary"],
            "excludedResourceIds": [],
            "dataZone": None,
            "ownerScope": None,
            "labels": {},
            "maxCost": None,
            "preferences": {},
            "policyMetadata": {"source": "prepared-run", "stepId": "analyse"},
        }
    }


def test_acg_execution_uses_frozen_agent_binding_after_registry_changes() -> None:
    """准备后新增更高优先级 Agent 不能改变已准备运行的执行绑定。"""
    calls: list[str] = []
    runtime, agents = _runtime(calls)
    task = runtime.create_task("resource", workflow_id="resource-run")
    _, run = runtime.prepare_run(task.task_id)
    agents.register(_BoundAgent(AgentProfile(
        agentId="agent-new", agentName="new", domain="general",
        capabilities=["analysis"], bindingPriority=99,
    ), calls))

    asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert calls == ["agent-primary"]
