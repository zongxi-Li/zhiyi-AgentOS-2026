"""Operator commands exercise the actual graph, stores, identity and Planner loop."""
import asyncio
import threading

import pytest

from contracts.planning import PlannedTask, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.runtime_planning import RuntimeUserInput
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from contracts.workflow import utc_now
from runtime.planning_interaction import CopilotMessageRequest, RuntimePlanningInteraction
from runtime.planning_operations import TaskOperationApplyRequest, TaskOperationPreviewRequest
from runtime.review import ReviewConflictError
from test_planning_loop import Agent, Planner, attach, prepared, runtime_at


def preview(service, run_id, kind, *, step=None, key="proposal", content="explicit operator request"):
    return asyncio.run(service.preview_operation(run_id, TaskOperationPreviewRequest(
        kind=kind, stepId=step, operationId=key, content=content, permission="task_collaboration")))


def apply(service, run_id, proposal, permission="task_collaboration"):
    return asyncio.run(service.operations.apply(run_id, TaskOperationApplyRequest(
        proposalId=proposal["operationId"], expectedRevision=proposal["action"]["expectedRevision"], permission=permission)))


def branching_workflow():
    return WorkflowDefinition(workflowId="seq", name="branching", domain="general", runtimeEngine="acg",
        planningNodes=tuple(PlannedTask(key=f"step:{s}", title=s, objective=f"do {s}") for s in "ABCDE"),
        planningRelations=tuple(TaskPlanRelation(sourceKey=f"step:{a}", targetKey=f"step:{b}", relationType="depends_on")
            for a, b in [("A", "B"), ("B", "C"), ("A", "D"), ("D", "E")]),
        steps=tuple(WorkflowStepDefinition(stepId=s, name=s, agentName="runner") for s in "ABCDE"))


def test_node_rerun_invalidates_descendants_preserves_parallel_branch_and_restarts(tmp_path):
    runtime, agent, run = prepared(tmp_path, workflow=branching_workflow())
    planner = Planner()
    attach(runtime, planner)
    original = asyncio.run(runtime.execute_prepared_run(run.run_id))
    before = original.model_dump(mode="json")
    service = RuntimePlanningInteraction(runtime)
    proposal = preview(service, run.run_id, "rerun_node", step="B")
    assert proposal["action"]["executeStepIds"] == ["B", "C"]
    assert proposal["action"]["reusedStepIds"] == ["A", "D", "E"]
    receipt = apply(service, run.run_id, proposal)
    child_id = receipt["receipt"]["runId"]
    child = runtime.workflow_store.get_run(child_id)
    assert set(child.execution_state["outputRefs"]) == {"A", "D", "E"}
    assert all(s.status.value == "pending" for s in child.steps if s.step_id in {"B", "C"})
    assert child.execution_state["nodeRerun"]["invalidatedStepIds"] == ["B", "C"]
    assert runtime.workflow_store.get_run(run.run_id).model_dump(mode="json") == before
    assert apply(service, run.run_id, proposal) == receipt
    recovered, new_agent = runtime_at(tmp_path, workflow=branching_workflow())
    attach(recovered, planner)
    asyncio.run(recovered.close_orphaned_runs())
    result = asyncio.run(recovered.execute_prepared_run(child_id))
    assert result.status == WorkflowStatus.COMPLETED and new_agent.calls == ["B", "C"]
    assert planner.observations[-1].steps[0].audit_outcome == "allow"
    assert len(recovered.workflow_store.list_runs(mission_id=run.mission_id).items) == 2
    chained = preview(RuntimePlanningInteraction(recovered), child_id, "rerun_node", step="C", key="chain")
    assert chained["action"]["reusedStepIds"] == ["A", "B", "D", "E"]


def test_rerun_copies_frozen_inputs_and_confirmation_cannot_escalate_or_change_target(tmp_path):
    runtime, agent, run = prepared(tmp_path, input={"userInput": "frozen source", "custom": "source"})
    attach(runtime, Planner())
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    mission = runtime.workflow_store.get_mission(run.mission_id)
    mission.input["custom"] = "later edit"
    runtime.workflow_store.save_mission(mission)
    service = RuntimePlanningInteraction(runtime)
    proposal = preview(service, run.run_id, "rerun")
    with pytest.raises(ValueError):
        apply(service, run.run_id, proposal, "read_only")
    receipt = apply(service, run.run_id, proposal)
    child = runtime.workflow_store.get_run(receipt["receipt"]["runId"])
    assert child.input["custom"] == "source"
    assert child.execution_scope == run.execution_scope
    assert child.execution_state["planningLoop"]["roundsUsed"] == 1
    assert asyncio.run(runtime.execute_prepared_run(child.run_id)).status == WorkflowStatus.COMPLETED
    assert agent.calls == ["A", "B", "A", "B"]
    with pytest.raises(ReviewConflictError):
        preview(service, run.run_id, "rerun_node", step="B")


def test_node_rerun_rejects_missing_checkpoint_and_stale_preview(tmp_path):
    runtime, _, run = prepared(tmp_path)
    attach(runtime, Planner())
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    service = RuntimePlanningInteraction(runtime)
    with pytest.raises((ValueError, KeyError)):
        preview(service, run.run_id, "rerun_node", step="unknown")
    proposal = preview(service, run.run_id, "rerun_node", step="A")
    changed = runtime.workflow_store.get_run(run.run_id)
    changed.runtime_revision += 1
    runtime.workflow_store.save_run(changed)
    with pytest.raises(ReviewConflictError):
        apply(service, run.run_id, proposal)
    changed.execution_state["checkpointId"] = "missing"
    runtime.workflow_store.save_run(changed)
    with pytest.raises(ValueError, match="checkpoint"):
        runtime.prepare_node_rerun(run.run_id, "B")
    assert runtime.workflow_store.list_runs(mission_id=run.mission_id).total == 1


def test_confirmed_input_is_durable_during_active_fragment_and_seen_by_planner(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class PausingAgent(Agent):
        async def run(self, context):
            if context.step.step_id == "A":
                entered.set()
                assert await asyncio.to_thread(release.wait, 10)
            return await super().run(context)
    runtime, agent, run = prepared(tmp_path, PausingAgent())
    planner = Planner()
    attach(runtime, planner)
    service = RuntimePlanningInteraction(runtime)
    async def scenario():
        worker = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
        assert await asyncio.to_thread(entered.wait, 10)
        proposal = await service.preview_operation(run.run_id, TaskOperationPreviewRequest(
            kind="user_input", operationId="new-requirement", content="请增加对比说明", permission="task_collaboration"))
        request = TaskOperationApplyRequest(proposalId=proposal["operationId"], expectedRevision=proposal["action"]["expectedRevision"], permission="task_collaboration")
        receipt = await service.operations.apply(run.run_id, request)
        release.set()
        result = await worker
        assert await service.operations.apply(run.run_id, request) == receipt
        return result
    result = asyncio.run(scenario())
    assert result.status == WorkflowStatus.COMPLETED
    assert [o.wake_reason for o in planner.observations] == ["user_input", "exhausted"]
    assert planner.observations[0].user_inputs[0].content == "请增加对比说明"
    assert agent.calls == ["A", "B"]
    assert len(runtime.workflow_store.list_planning_inputs(run.run_id)) == 1


def test_input_wait_wakeup_survives_restart_without_approving_review(tmp_path):
    runtime, _, run = prepared(tmp_path)
    planner = Planner(lambda o, p: RuntimePlanningDecision(observationId=o.fingerprint(),
        action="wait" if not o.user_inputs else "complete", reason="requires operator input"))
    attach(runtime, planner)
    waiting = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert waiting.status == WorkflowStatus.WAITING_REVIEW
    service = RuntimePlanningInteraction(runtime)
    with pytest.raises(ValueError, match="失败恢复"):
        preview(service, run.run_id, "recover", key="cannot-bypass-wait")
    proposal = preview(service, run.run_id, "user_input", content="采用当前结果并继续评估")
    apply(service, run.run_id, proposal)
    recovered, agent2 = runtime_at(tmp_path)
    attach(recovered, planner)
    assert asyncio.run(recovered.prepare_planning_wakeups()) == [run.run_id]
    result = asyncio.run(recovered.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED and agent2.calls == []
    assert planner.observations[-1].wake_reason == "user_input"
    assert not any(e.event_type.value == "review_decided" for e in result.trace)


def test_natural_language_only_prepares_validated_action_and_readonly_cannot_act(tmp_path):
    runtime, agent, run = prepared(tmp_path)
    attach(runtime, Planner())
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"content": "可以从 B 重跑。", "action": {"kind": "rerun_node", "stepId": "B"}}
    runtime.set_intent_llm(Model())
    service = RuntimePlanningInteraction(runtime)
    exchange = asyncio.run(service.message(run.run_id, CopilotMessageRequest(operationId="natural", content="从 B 重跑")))
    assert exchange["action"]["executeStepIds"] == ["B"] and agent.calls == ["A", "B"]
    readonly = asyncio.run(service.message(run.run_id, CopilotMessageRequest(operationId="readonly", content="从 B 重跑", permission="read_only")))
    assert "action" not in readonly
    assert runtime.workflow_store.list_runs(mission_id=run.mission_id).total == 1


def test_recover_routes_through_existing_failed_step_authority(tmp_path):
    runtime, agent, run = prepared(tmp_path, Agent(fail=True))
    attach(runtime, Planner(lambda o, p: RuntimePlanningDecision(observationId=o.fingerprint(), action="abort", reason="leave for operator")))
    with pytest.raises(Exception, match="ACG superstep failed"):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    failed = runtime.workflow_store.get_run(run.run_id)
    assert failed.status == WorkflowStatus.FAILED
    service = RuntimePlanningInteraction(runtime)
    proposal = preview(service, run.run_id, "recover")
    receipt = apply(service, run.run_id, proposal)
    attach(runtime, Planner())
    assert asyncio.run(runtime.execute_prepared_run(receipt["receipt"]["runId"])).status == WorkflowStatus.COMPLETED
    assert agent.calls == ["A", "B", "B"]


def test_same_timestamp_outbox_keeps_transactional_causal_order(tmp_path):
    runtime, _, run = prepared(tmp_path)
    store = runtime.workflow_store
    events = [{"eventId": key, "eventType": "test", "aggregateId": run.run_id, "payload": {}}
              for key in ("z:run", "a:attempt", "c:resource", "b:started")]
    store.save_run_with_events(run, events)
    with store._connect() as conn:
        conn.execute("UPDATE lifecycle_outbox SET created_at='2026-10-05 00:00:00' WHERE event_type='test'")
    assert [e["event_id"] for e in store.list_outbox() if e["event_type"] == "test"] == [e["eventId"] for e in events]


def test_operator_input_arriving_during_decision_prevents_stale_completion(tmp_path):
    runtime, agent, run = prepared(tmp_path)
    def choose(observation, plan):
        if not observation.user_inputs:
            item = RuntimeUserInput(sourceRunId=run.run_id, operationId="during-decision",
                content="Check this additional requirement", submittedAt=utc_now())
            runtime.workflow_store.save_planning_input(run.run_id, item.operation_id, item.model_dump(by_alias=True, mode="json"))
        return RuntimePlanningDecision(observationId=observation.fingerprint(), action="complete", reason="current evidence")
    planner = Planner(choose)
    attach(runtime, planner)
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED and agent.calls == ["A", "B"]
    assert [o.wake_reason for o in planner.observations] == ["exhausted", "user_input"]
    assert planner.observations[-1].user_inputs[0].operation_id == "during-decision"


def test_node_rerun_is_not_published_before_reused_results_are_ready(tmp_path, monkeypatch):
    runtime, _, run = prepared(tmp_path)
    attach(runtime, Planner())
    source = asyncio.run(runtime.execute_prepared_run(run.run_id))
    before = source.model_dump(mode="json")
    service = RuntimePlanningInteraction(runtime)
    proposal = preview(service, run.run_id, "rerun_node", step="B")
    original_save = runtime.workflow_store.save_run_with_events
    def interrupted(candidate, events):
        if candidate.run_id != source.run_id:
            raise RuntimeError("interrupted before atomic publication")
        return original_save(candidate, events)
    monkeypatch.setattr(runtime.workflow_store, "save_run_with_events", interrupted)
    with pytest.raises(RuntimeError, match="atomic publication"):
        apply(service, run.run_id, proposal)
    assert runtime.workflow_store.list_runs(mission_id=source.mission_id).total == 1
    assert runtime.workflow_store.get_run(source.run_id).model_dump(mode="json") == before
    monkeypatch.setattr(runtime.workflow_store, "save_run_with_events", original_save)
    receipt = apply(service, run.run_id, proposal)
    assert receipt["receipt"]["runId"] != source.run_id
    assert runtime.workflow_store.list_runs(mission_id=source.mission_id).total == 2


def test_node_rerun_reenters_settled_verification_region_with_existing_loop_authority(tmp_path):
    from support.acg.schema import RuntimeBlueprintSpec, ControlNode, ACGEdge
    class LoopAgent(Agent):
        checks = 0
        async def run(self, context):
            result = await super().run(context)
            if context.step.step_id == "C":
                self.checks += 1
                result = result.model_copy(update={"output": {"verification": {"status": "passed"}}})
            return result
    workflow = branching_workflow().model_copy(update={"planning_relations": tuple(
        TaskPlanRelation(sourceKey=f"step:{a}", targetKey=f"step:{b}", relationType="depends_on")
        for a, b in [("A", "B"), ("B", "C"), ("C", "D"), ("A", "E")])})
    runtime, agent, base = prepared(tmp_path, LoopAgent(), workflow=workflow)
    policy = {"bodyEntryKey": "step:B", "bodyExitKey": "step:C", "conditionSourceKey": "step:C"}
    plan = {**base.execution_state["taskPlan"], "controlPolicies": [policy]}
    blueprint = RuntimeBlueprintSpec.model_validate(base.acg_blueprint)
    edge = ACGEdge(sourceId="ctrl_verification_loop_1", targetId="B", edgeType="dependency")
    blueprint.edges.append(edge)
    blueprint.nodes.append(ControlNode(nodeId="ctrl_verification_loop_1", name="verify loop", controlType="loop",
        metadata={"taskPlanPolicy": "verification_loop", "maxRevisions": 2}, loopSpec={
            "bodyEntryId": "B", "bodyExitId": "C", "maxIterations": 3, "condition": {
                "sourceNodeId": "C", "jsonPointer": "/verification/status", "operator": "IN",
                "cases": {"partial": edge.edge_id, "failed": edge.edge_id}}}))
    _, run = runtime.prepare_run(base.mission_id, input_override={"taskPlan": plan,
        "taskBindings": base.execution_state["taskBindings"], "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json")})
    attach(runtime, Planner())
    source = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert source.status == WorkflowStatus.COMPLETED and agent.checks == 1
    assert source.execution_state["loopIterations"] == {}
    service = RuntimePlanningInteraction(runtime)
    proposal = preview(service, run.run_id, "rerun_node", step="C")
    assert proposal["action"]["executeStepIds"] == ["B", "C", "D"]
    assert proposal["action"]["reusedStepIds"] == ["A", "E"]
    receipt = apply(service, run.run_id, proposal)
    child_id = receipt["receipt"]["runId"]
    recovered, new_agent = runtime_at(tmp_path, LoopAgent(), workflow=workflow)
    attach(recovered, Planner())
    result = asyncio.run(recovered.execute_prepared_run(child_id))
    assert result.status == WorkflowStatus.COMPLETED and new_agent.calls == ["B", "C", "D"]
    # Selecting a downstream node must keep the unaffected settled control.
    downstream = preview(RuntimePlanningInteraction(recovered), child_id, "rerun_node", step="D", key="downstream")
    assert downstream["action"]["executeStepIds"] == ["D"]
    assert downstream["action"]["reusedStepIds"] == ["A", "B", "C", "E"]
    receipt = apply(RuntimePlanningInteraction(recovered), child_id, downstream)
    result = asyncio.run(recovered.execute_prepared_run(receipt["receipt"]["runId"]))
    assert result.status == WorkflowStatus.COMPLETED and new_agent.calls == ["B", "C", "D", "D"]
