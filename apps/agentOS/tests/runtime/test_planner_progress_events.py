"""Planner Runtime Event 合同：Model Output 只显示可被 Trace 证明的事实。

锁定 2026-09 审计后的合同：
- Planner 路径产生 started / stage_started / stage_completed / retry /
  profile_resolved / plan_parsed / graph_compiled / completed / failed 事件；
- 所有计数（taskCount、dependencyCount、nodeCount、edgeCount、constraintCount）
  必须与真实 TaskPlan / ACG 蓝图一致，禁止转述或伪造；
- 显式 Blueprint 兼容入口不伪造 Planner 事件；
- 事件 payload 走白名单，prompt / 模型文本 / reasoning 永远进不了 Trace。
"""

from __future__ import annotations


import asyncio

import pytest

from runtime.workflow_runtime import ExecutionRuntime
from components.mission_manager.store import WorkflowRegistry
from service.agents import AgentRegistry, AgentProfile, BaseAgent, AgentOutput
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from contracts.planning import TaskImplementationBinding, TaskPlan, PlannedTask
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.acg.planning import ACGResourcePlan, AgentBindingSpec, CommunicationSpec
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode


class Runner(BaseAgent):
    async def run(self, context):
        return AgentOutput(output={"task_summary": "done", "constraints": []}, summary="ok")


def _runtime(*, agent_capabilities: list[str] | None = None) -> ExecutionRuntime:
    agents = AgentRegistry()
    agents.register(Runner(AgentProfile(
        agentName="runner", domain="general", capabilities=agent_capabilities or [],
    )))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="acg-run", name="ACG run", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="extract", name="extract", agentName="runner")],
    ))
    return ExecutionRuntime(
        agent_registry=agents, workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )


def _planner_events(runtime: ExecutionRuntime, run_id: str) -> list[dict]:
    run = runtime.workflow_store.get_run(run_id)
    return [
        event.payload for event in run.trace
        if isinstance(event.payload, dict) and event.payload.get("planningProgress")
    ]


def test_planner_path_emits_fact_event_chain_with_true_counts() -> None:
    """Planner 路径必须产生事实事件链，计数与真实 TaskPlan/蓝图一致。"""
    runtime = _runtime(agent_capabilities=[
        "task_understanding", "analysis", "artifact_generation", "verification",
    ])
    task = runtime.create_mission("planner run", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.mission_id, input_override={"forceDynamicPlanning": True})
    try:
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    except Exception:
        pass  # 执行阶段的节点输出合同与本测试无关；只验证规划事件。

    events = _planner_events(runtime, run.run_id)
    kinds = [str(event.get("kind")) for event in events]

    assert kinds[0] == "started"
    assert "plan_parsed" in kinds
    assert "graph_compiled" in kinds
    assert kinds[-1] == "completed"

    saved = runtime.workflow_store.get_run(run.run_id)
    task_plan = saved.execution_state["taskPlan"]
    compiled_package = saved.execution_state["compiledACGPackage"]

    parsed = next(event for event in events if event.get("kind") == "plan_parsed")
    assert parsed["category"] == "planner"
    assert parsed["taskCount"] == len(task_plan["nodes"])
    assert parsed["dependencyCount"] == len(task_plan["relations"])
    assert parsed["nodes"]
    assert parsed["nodes"][0]["key"] == task_plan["nodes"][0]["key"]
    assert "objective" in parsed["nodes"][0]
    assert parsed["relations"] == task_plan["relations"]

    # graph_compiled 计数取自编译产物，而不是编译输入蓝图。
    compiled = next(event for event in events if event.get("kind") == "graph_compiled")
    assert compiled["nodeCount"] == len(compiled_package["nodes"])
    assert compiled["edgeCount"] == len(compiled_package["edges"])

    decision_event = next(
        event for event in saved.trace
        if event.observation.startswith("Planner produced ACG via")
    )
    topology_audit = decision_event.payload["topologyAudit"]
    assert topology_audit["compilerVersion"]
    assert topology_audit["catalogFingerprint"]
    assert topology_audit["topologyFingerprint"]
    assert topology_audit["status"] == "validated"
    assert saved.execution_state["topologyAudit"] == topology_audit
    assert saved.acg_blueprint["metadata"]["topologyAudit"] == topology_audit

    for event in events:
        assert event["category"] == "planner"
        assert event.get("planningProgress") is True


def test_planner_failure_emits_failed_event_without_leaking_error_text() -> None:
    """Planner 失败必须落 failed 事件；异常消息细节不得进入 Trace。"""
    runtime = _runtime(agent_capabilities=[])  # 无能力 → unresolved → ACGPlanningError
    task = runtime.create_mission("doomed planning", workflow_id="acg-run")
    with pytest.raises(Exception):
        # prepare_run 不带 defer 时同步物化，规划失败在此时抛出。
        runtime.prepare_run(task.mission_id, input_override={"forceDynamicPlanning": True})

    # failed 事件随 save_run 落库；run_id 未知，按 mission 从 store 反查。
    saved_runs = runtime.workflow_store.list_runs(mission_id=task.mission_id)
    assert saved_runs.items, "failed run must be persisted"
    events = _planner_events(runtime, saved_runs.items[0].run_id)
    failures = [event for event in events if event.get("kind") == "failed"]
    assert failures, "planner failure must emit a failed event"
    failure = failures[-1]
    assert failure["errorCode"] == "ACGPlanningError"
    assert failure["safeSummary"] == "ACGPlanningError during planning"

    serialized = repr(events)
    assert "No registered Agent" not in serialized
    assert "reasoning" not in serialized.lower()


def test_explicit_blueprint_path_never_fakes_planner_events() -> None:
    """显式 Blueprint 兼容入口没有 Planner 运行，不得出现 planner 事件。"""
    runtime = _runtime()
    task = runtime.create_mission("explicit run", workflow_id="acg-run")

    step = StepNode(nodeId="node-1", key="extract", capability="analysis")
    blueprint = ACGBlueprint(
        missionId=task.mission_id, graphId="graph-explicit",
        nodes=[step],
        resourcePlan=ACGResourcePlan(bindings=(AgentBindingSpec(stepId="node-1", plannedAgentId="runner"),)),
        edges=[],
    )
    task_plan = TaskPlan(
        missionId=task.mission_id, planVersion=1,
        nodes=[PlannedTask(
            key="extract", title="extract", objective="complete the extract step",
            capabilityRequirements=["analysis"],
        )],
        relations=[],
    )
    bindings = [TaskImplementationBinding(planNodeKey="extract", acgNodeId="node-1")]
    _, run = runtime.prepare_run(
        task.mission_id,
        input_override={
            "acgBlueprint": blueprint.model_dump(by_alias=True),
            "taskPlan": task_plan.model_dump(by_alias=True),
            "taskBindings": [item.model_dump(by_alias=True) for item in bindings],
        },
    )
    try:
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    except Exception:
        pass

    kinds = [str(event.get("kind")) for event in _planner_events(runtime, run.run_id)]
    assert "started" not in kinds
    assert "plan_parsed" not in kinds
    assert "graph_compiled" not in kinds
    assert "completed" not in kinds
    assert "failed" not in kinds


def test_planner_event_payload_whitelist_drops_unsafe_fields() -> None:
    """白名单是安全边界：prompt / 模型文本即使被塞进事件也必须被丢弃。"""
    runtime = _runtime()
    task = runtime.create_mission("whitelist", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.mission_id)

    runtime._append_planner_event(run, {
        "kind": "stage_started",
        "stage": "intent_profile",
        "status": "started",
        "prompt": "SECRET PROMPT BODY",
        "reasoning": "SECRET REASONING",
        "modelOutput": '{"tasks": []}',
    })

    events = _planner_events(runtime, run.run_id)
    assert len(events) == 1
    payload = events[0]
    assert payload["kind"] == "stage_started"
    assert payload["stage"] == "intent_profile"
    assert "prompt" not in payload
    assert "reasoning" not in payload
    assert "modelOutput" not in payload
    assert "SECRET" not in repr(payload)


def test_plan_parsed_projects_only_safe_task_plan_fields() -> None:
    runtime = _runtime()
    task = runtime.create_mission("plan projection", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.mission_id)

    runtime._append_planner_event(run, {
        "status": "plan_parsed", "taskCount": 1, "dependencyCount": 1,
        "nodes": [{
            "key": "design", "title": "Design", "objective": "Create the design",
            "capabilityRequirements": ["analysis"], "acceptanceCriteria": ["reviewed"],
            "producedArtifacts": ["report"], "logicalRole": "task",
            "prompt": "SECRET", "agentName": "SECRET",
        }],
        "relations": [{
            "sourceKey": "design", "targetKey": "review", "relationType": "depends_on",
            "reasoning": "SECRET",
        }],
    })

    parsed = _planner_events(runtime, run.run_id)[-1]
    assert parsed["nodes"][0]["objective"] == "Create the design"
    assert parsed["nodes"][0]["capabilityRequirements"] == ["analysis"]
    assert parsed["relations"][0] == {
        "sourceKey": "design", "targetKey": "review", "relationType": "depends_on",
    }
    assert "SECRET" not in repr(parsed)


def test_planner_failed_trace_accepts_only_structured_topology_audit() -> None:
    runtime = _runtime()
    task = runtime.create_mission("topology failure audit", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.mission_id)
    safe_audit = {
        "compilerVersion": "task-plan-topology-v5b",
        "catalogFingerprint": "a" * 64,
        "topologyFingerprint": "b" * 64,
        "status": "rejected",
        "conflict": {
            "code": "dependency_cycle", "phase": "final_validation",
            "cycleNodes": ["A", "B", "A"],
            "cycleEdges": [{"origin": "plan_patch", "mutationPolicy": "fixed"}],
        },
    }
    runtime._append_planner_event(run, {
        "kind": "failed", "errorCode": "dependency_cycle",
        "safeSummary": "TopologyCompileError during planning",
        "topologyAudit": {**safe_audit, "prompt": "NESTED SECRET", "rawResponse": "SECRET"},
        "prompt": "SECRET",
    })
    failure = _planner_events(runtime, run.run_id)[-1]
    assert failure["topologyAudit"]["compilerVersion"] == safe_audit["compilerVersion"]
    assert failure["topologyAudit"]["topologyFingerprint"] == safe_audit["topologyFingerprint"]
    assert failure["topologyAudit"]["conflict"]["code"] == "dependency_cycle"
    assert "prompt" not in failure
    assert "prompt" not in failure["topologyAudit"]
    assert "rawResponse" not in failure["topologyAudit"]
    assert "SECRET" not in repr(failure)
