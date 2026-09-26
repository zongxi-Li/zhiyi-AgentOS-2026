"""运行取消语义与并发恢复互斥的回归测试。

历史缺陷：
1. ``cancel`` 只把存储中的运行落为 CANCELLED，不向仍在 ``astream`` 循环里的
   执行任务发送任何信号——图会继续跑完后继步骤并消耗 Agent/模型调用；随后
   完成路径对已取消的任务调用 ``mark_completed`` 触发非法状态迁移（cancelled
   -> completed），执行协程以 ``InvalidStateTransition`` 崩溃。
2. ``resume_from_checkpoint`` 在进入执行前没有互斥保护：两次并发恢复都会通过
   检查，对同一批未提交步骤并发发起 Agent 调用并互相踩踏持久化状态。

本文件锁定修复后的合同：
- 取消请求发出后不再调度任何新步骤，执行任务正常返回 CANCELLED 投影；
- 并发恢复同一运行时恰好只有一个执行者在跑，另一路立即被拒绝。
"""

from __future__ import annotations


import asyncio
import threading

import pytest

from runtime.workflow_runtime import ExecutionRuntime
from components.mission_manager.store import WorkflowRegistry
from contracts.workflow import ReviewDecision, ReviewDecisionType, WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode, AgentNode


class _GatedAgent(BaseAgent):
    """记录每一次真实调用；可选地在指定步骤挂起以制造确定性执行窗口。"""

    def __init__(self, profile: AgentProfile, *, blocked_step: str | None = None) -> None:
        super().__init__(profile)
        self.blocked_step = blocked_step
        self.arrived = asyncio.Event()
        self.gate = asyncio.Event()
        self.calls: list[str] = []

    async def run(self, context):
        step_id = context.step.step_id
        self.calls.append(step_id)
        if step_id == self.blocked_step:
            self.arrived.set()
            await self.gate.wait()
        return AgentOutput(output={"summary": f"done:{step_id}"}, summary=f"done:{step_id}")


def _registry(agent_name: str, agent: BaseAgent, *, workflow_id: str):
    agents = AgentRegistry()
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId=workflow_id,
            name="cancellation probe",
            domain="general",
            runtimeEngine="acg",
            steps=[WorkflowStepDefinition(stepId="bootstrap", name="bootstrap", agentName=agent_name)],
        )
    )
    return agents, workflows


def test_cancel_midstream_stops_graph_and_returns_cancelled(monkeypatch) -> None:
    """取消后不得再执行任何新步骤，且执行任务必须干净收敛到 CANCELLED。"""
    gated = _GatedAgent(
        AgentProfile(agentName="gated", domain="general"),
        blocked_step="blocker",
    )

    async def scenario():
        agents, workflows = _registry("gated", gated, workflow_id="cancel-probe")
        runtime = ExecutionRuntime(
            agent_registry=agents,
            workflow_registry=workflows,
            workflow_store=MemoryWorkflowStore(),
        )
        blueprint = ACGBlueprint(
            graphId="cancel-probe-graph",
            nodes=[
                StepNode(
                    nodeId="blocker",

                    outputSpec={"type": "object", "properties": {"title": {"type": "string"}}},
                ),
                StepNode(
                    nodeId="follower",

                    input={"from": {"blocker": ["title"]}},
                    outputSpec={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                    },
                ),
            AgentNode(nodeId="fixture-agent::blocker", name="gated"), AgentNode(nodeId="fixture-agent::follower", name="gated")],
            edges=[ACGEdge(sourceId="blocker", targetId="follower", edgeType=EdgeType.DEPENDENCY), ACGEdge(sourceId="fixture-agent::blocker", targetId="blocker", edgeType=EdgeType.EXECUTION), ACGEdge(sourceId="fixture-agent::follower", targetId="follower", edgeType=EdgeType.EXECUTION)],
        )
        monkeypatch.setattr(
            runtime,
            "_build_acg_blueprint",
            lambda *_args, **_kwargs: (blueprint, None, ()),
        )
        mission = runtime.create_mission("cancel probe", workflow_id="cancel-probe")
        _, run = runtime.prepare_run(mission.mission_id)

        exec_task = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
        await asyncio.wait_for(gated.arrived.wait(), timeout=5)
        cancelled = runtime.cancel(run.run_id)
        assert cancelled.status is WorkflowStatus.CANCELLED

        gated.gate.set()
        # 修复前：图继续跑完 follower，然后完成路径对已取消任务调用
        # mark_completed 抛 InvalidStateTransition，这里会直接收到异常。
        result = await asyncio.wait_for(exec_task, timeout=10)
        return result

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.CANCELLED
    # 取消之后，下游 follower 步骤不得再获得任何一次 Agent 调用。
    assert gated.calls.count("follower") == 0


def test_cancel_during_deferred_planning_does_not_materialize_or_restart(monkeypatch) -> None:
    """规划线程返回后，取消终态不得被旧快照覆盖，也不得重新启动执行。"""
    gated = _GatedAgent(AgentProfile(agentName="gated", domain="general"))
    agents, workflows = _registry("gated", gated, workflow_id="cancel-planning")
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )
    blueprint = ACGBlueprint(
        graphId="cancel-planning-graph",
        nodes=[
            StepNode(
                nodeId="only-step",

                outputSpec={"type": "object", "properties": {"summary": {"type": "string"}}},
            )
        , AgentNode(nodeId="fixture-agent::only-step", name="gated")],
    edges=[ACGEdge(sourceId="fixture-agent::only-step", targetId="only-step", edgeType=EdgeType.EXECUTION)])
    planner_started = threading.Event()
    release_planner = threading.Event()

    def blocked_planner(*_args, **_kwargs):
        planner_started.set()
        assert release_planner.wait(timeout=5)
        return blueprint, None, ()

    monkeypatch.setattr(runtime, "_build_acg_blueprint", blocked_planner)
    mission = runtime.create_mission("cancel during planning", workflow_id="cancel-planning")
    _, run = runtime.prepare_run(mission.mission_id, defer_acg_planning=True)

    async def scenario():
        execution = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
        await asyncio.wait_for(asyncio.to_thread(planner_started.wait, 5), timeout=6)
        cancelled = runtime.cancel(run.run_id)
        release_planner.set()
        result = await asyncio.wait_for(execution, timeout=10)
        repeated = await runtime.execute_prepared_run(run.run_id)
        return cancelled, result, repeated

    try:
        cancelled, result, repeated = asyncio.run(scenario())
    finally:
        release_planner.set()

    assert cancelled.status is WorkflowStatus.CANCELLED
    assert result.status is WorkflowStatus.CANCELLED
    assert repeated.status is WorkflowStatus.CANCELLED
    latest = runtime.workflow_store.get_run(run.run_id)
    assert latest.status is WorkflowStatus.CANCELLED
    assert latest.acg_blueprint is None
    assert latest.execution_state["planningDeferred"] is True


def test_concurrent_checkpoint_resume_allows_exactly_one_executor(monkeypatch) -> None:
    """同一运行同时只允许一个执行体：活跃执行期间的第二次进入必须被立刻拒绝。

    确定性窗口分两段：
    1. 首步声明蓝图级 ``reviewRequired`` 触发步骤级审核中断并留下检查点；
    2. 审批恢复后的收尾 deliver 步骤阻塞在闸门上——此执行体必然持有执行槽；
       此时直接发起第二次进入，应当场撞上互斥保护，而不是靠调度运气。
    """
    gated = _GatedAgent(
        AgentProfile(agentName="voter", domain="general"),
        blocked_step="deliver",
    )

    async def scenario():
        agents, workflows = _registry("voter", gated, workflow_id="control-review")
        runtime = ExecutionRuntime(
            agent_registry=agents,
            workflow_registry=workflows,
            workflow_store=MemoryWorkflowStore(),
        )
        blueprint = ACGBlueprint(
            graphId="acg-race-graph",
            nodes=[
                StepNode(
                    nodeId="bootstrap",

                    reviewRequired=True,
                    outputSpec={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                    },
                ),
                StepNode(
                    nodeId="deliver",

                    input={"from": {"bootstrap": ["summary"]}},
                    outputSpec={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                    },
                ),
            AgentNode(nodeId="fixture-agent::bootstrap", name="voter"), AgentNode(nodeId="fixture-agent::deliver", name="voter")],
            edges=[ACGEdge(sourceId="bootstrap", targetId="deliver", edgeType=EdgeType.DEPENDENCY), ACGEdge(sourceId="fixture-agent::bootstrap", targetId="bootstrap", edgeType=EdgeType.EXECUTION), ACGEdge(sourceId="fixture-agent::deliver", targetId="deliver", edgeType=EdgeType.EXECUTION)],
        )
        monkeypatch.setattr(
            runtime,
            "_build_acg_blueprint",
            lambda *_args, **_kwargs: (blueprint, None, ()),
        )
        mission = runtime.create_mission("race probe", workflow_id="control-review")
        _, run = runtime.prepare_run(mission.mission_id)

        paused = await runtime.execute_prepared_run(run.run_id)
        assert paused.status is WorkflowStatus.WAITING_REVIEW
        assert gated.calls == ["bootstrap"]

        # 合法的审批恢复在后台执行；它会一路跑到 deliver 并停在闸门上。
        approved_resume = asyncio.create_task(runtime.apply_review(ReviewDecision(
            runId=run.run_id,
            stepId="bootstrap",
            decision=ReviewDecisionType.APPROVED,
            operationId="approve-bootstrap-race",
        )))
        await asyncio.wait_for(gated.arrived.wait(), timeout=5)

        checkpoint_id = runtime.checkpoint_store.load_latest(run_id=run.run_id)[0]
        try:
            await asyncio.wait_for(
                runtime.resume_from_checkpoint(run_id=run.run_id, checkpoint_id=checkpoint_id),
                timeout=2,
            )
            second_entry = None
        except ValueError as exc:
            second_entry = exc
        except TimeoutError:
            # 修复前的真实形态：第二路也进入了执行，双跑同一个收尾步骤。
            pytest.fail(
                "second entry ran concurrently instead of being rejected: "
                f"deliver invoked {gated.calls.count('deliver')}x"
            )

        assert second_entry is not None
        assert "already" in str(second_entry)

        # 解除闸门放行唯一执行体，等待其自然收敛，避免悬挂任务泄漏。
        gated.gate.set()
        winner = await asyncio.wait_for(approved_resume, timeout=10)
        return winner

    winner = asyncio.run(scenario())

    assert winner.status is WorkflowStatus.COMPLETED
    # 收尾 deliver 步骤全程只允许真实执行一次。
    assert gated.calls.count("deliver") == 1
