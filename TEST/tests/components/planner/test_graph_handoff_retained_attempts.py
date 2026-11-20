"""Keep genuine failed-operation identities across successive graph handoffs."""
import asyncio
import json

import pytest

from components.executor.node_runner import ACGNodeRunner
from contracts.execution import NodeExecutionPhase, NodeExecutionRecord
from contracts.workflow import WorkflowStatus
from domain.identity_graph.bindings import ExecutionBinding
from domain.models import Attempt, StepExecution
from TEST.tests.components.planner.test_execution_permit import ready_handoff as ready_handoff
from TEST.tests.components.planner.test_graph_handoff_generation import activate_next_graph, next_activation


def cancelled_native_history(tmp_path):
    """A real completed prefix plus a cancelled native read awaiting retry."""
    from adapters.agent.native import NativeGeneralAgent
    from contracts.acg.planning import CommunicationSpec
    from components.mission.semantic_service import MissionSemanticService
    from contracts.capability import ModelInvocationResponse
    from contracts.local_runtime import LocalRuntimeExecutionRequest
    from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal
    from contracts.planning import PlannedTask, TaskPlanRelation
    from contracts.runtime_planning import RuntimePlanningDecision
    from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
    from support.stores.graph_activation_store import SQLiteGraphActivationStore
    from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
    from support.stores.execution_permit_store import SQLiteExecutionPermitStore
    from TEST.tests.components.planner.test_graph_handoff import attach as attach_handoff
    from TEST.tests.components.planner.test_planning_commit_runtime import attach
    from TEST.tests.components.planner.test_react_loop import runtime_at

    rt, workflow, agent = runtime_at(tmp_path)
    native = NativeGeneralAgent()
    native.profile.capabilities = ["information_extraction"]
    rt.agent_registry.register(native)
    registration = rt.agent_registry.registration_for(native)
    rt.workflow_registry.register(WorkflowDefinition(workflowId="native-history", name="native-history",
        domain="general", runtimeEngine="acg", planningNodes=(
            PlannedTask(key="step:A", title="A", objective="understand", capabilityRequirements=("task_understanding",)),
            PlannedTask(key="step:C", title="C", objective="read", capabilityRequirements=("information_extraction",))),
        planningRelations=(TaskPlanRelation(sourceKey="step:A", targetKey="step:C", relationType="depends_on"),),
        steps=(WorkflowStepDefinition(stepId="A", name="A", agentName="runner", capability="task_understanding"),
               WorkflowStepDefinition(stepId="C", name="C", agentName=native.profile.agent_name,
                   capability="information_extraction"))))
    workflow._init_semantic_schema()
    workflow.enable_existing_mission_semantics()
    owner = SemanticPrincipal(actorId="owner", tenantId="tenant")
    rt.mission_semantic_service = MissionSemanticService(store=workflow, authorize=lambda p, m, a: p == owner)
    rt.semantic_principal_provider = lambda: owner
    rt.allow_legacy_mission_intent = False
    mission = rt.create_mission("native history", workflow_id="native-history",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}})
    rt.mission_semantic_service.commit(owner, MissionSemanticRequest(missionId=mission.mission_id,
        operationId="basis", expectedMissionRevision=0, objective="Review native evidence", constraints=[], sourceRefs=[]))

    class Pause:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if observation.completed_step_ids else "continue", reason="inspect prefix")

    rt.runtime_planning_coordinator.planner_for_run = lambda _: Pause()
    boundary = rt.runtime_planning_coordinator.boundary

    async def observe(run, state, reason):
        return await boundary(run, state, "resume" if state.completed_step_ids else reason)

    rt.runtime_planning_coordinator.boundary = observe
    build = rt._build_acg_blueprint

    def complete_graph(*args, **kwargs):
        blueprint, plan, bindings = build(*args, **kwargs)
        blueprint.resource_plan = blueprint.resource_plan.model_copy(update={"communication": (
            CommunicationSpec(producerStepId="A", consumerStepId="C", channel="A:C"),)})
        return blueprint, plan, bindings

    rt._build_acg_blueprint = complete_graph
    _, run = rt.prepare_run(mission.mission_id)
    paused = asyncio.run(rt.execute_prepared_run(run.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A"]
    repos = rt.identity_lifecycle.repositories
    identity = repos.runs.get(run.run_id)
    task_id = repos.task_bindings.find_for_acg_node("C", identity.blueprint_id)[0].task_id
    attempt = Attempt(runId=run.run_id, taskId=task_id, attemptNumber=1, status="cancelled")
    repos.attempts.add(attempt)
    repos.step_executions.add(StepExecution(runId=run.run_id, taskId=task_id,
        attemptId=attempt.attempt_id, status="cancelled"))
    repos.execution_bindings.add(ExecutionBinding(attemptId=attempt.attempt_id, acgNodeId="C",
        resourceId="native", agentId=registration.agent_id, modelId="none",
        metadata={"agentRegistration": registration.model_dump(by_alias=True, mode="json")}))
    operation = ACGNodeRunner._commit_id(run.run_id, "C", 0)
    rt.execution_value_store.prepare_node_commit(run_id=run.run_id, commit_id=operation)
    node = NodeExecutionRecord(operationId=operation, executionInstanceId=f"{run.run_id}:C:0:root",
        runId=run.run_id, stepId="C", attemptId=attempt.attempt_id, phase="prepared")
    rt.execution_value_store.transition_node_execution(node)
    response = ModelInvocationResponse(requestId="native-turn", content={}, provider="test", model="mock",
        toolCalls=[{"id": "read", "type": "function", "function": {"name": "fs__list", "arguments": json.dumps({"path": "."})}}])
    rt.execution_value_store.put_tool_value(run_id=run.run_id, step_id="C", key=operation + ":tools:0:model-turn",
        payload={"requestHash": "a" * 64, "response": response.model_dump(by_alias=True, mode="json")})
    read = operation + ":tools:0:call:0"
    request = LocalRuntimeExecutionRequest(protocolVersion="1", requestId=read, invocationId=read,
        resourceId="hands", capabilityId="fs.list", authorization={"workspaceId": "workspace", "grantId": "grant"},
        input={"path": "."}, limits={"timeoutSeconds": 90, "maxStdoutBytes": 64000, "maxStderrBytes": 32000},
        idempotencyKey=read)
    rt.execution_value_store.put_tool_value(run_id=run.run_id, step_id="C", key=read + ":request",
        payload={"request": request.model_dump(by_alias=True, mode="json"), "identity": {
            "runId": run.run_id, "stepId": "C", "attemptId": attempt.attempt_id, "commitId": operation}})
    paused = workflow.get_run(run.run_id)
    paused.get_step("C").attempt = paused.get_step("C").retry_count = 1
    paused.execution_state["taskSettlement"] = {attempt.attempt_id: {
        "taskState": "ended", "outcome": "cancelled", "leaseState": "released", "trigger": "worker_shutdown"}}
    workflow.save_run(paused)
    attach(rt, workflow)
    for store_type, enable in ((SQLiteGraphMaterializationStore, rt.enable_graph_materialization),
            (SQLiteGraphActivationStore, rt.enable_graph_activation)):
        store_type.upgrade_schema(workflow.db_path)
        enable(store_type(workflow.db_path))
    ledger, _ = attach_handoff(rt, workflow)
    SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
    rt.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    from runtime.orchestration.permit_recovery import assert_replay_safe_operations
    assert_replay_safe_operations(rt, workflow.get_run(run.run_id))
    return rt, workflow, agent, run.run_id, node, ledger


def test_cancelled_native_read_history_survives_successive_handoffs_without_relabeling(tmp_path):
    rt, workflow, agent, run_id, node, ledger = cancelled_native_history(tmp_path)
    receipts = rt.execution_value_store.list_node_commits(run_id=run_id)
    for version, added, predecessor in ((2, "D", "C"), (3, "E", "D")):
        before = workflow.get_run(run_id)
        activation = activate_next_graph(rt, before, key="native-history-" + str(version), node=added, predecessor=predecessor)
        result = rt.prepare_graph_handoff(activation, idempotency_key="native-history-handoff-" + str(version))
        assert result.status == "STATE_PREPARED", result
        record = ledger.get_handoff(result.handoff_id)
        assert record.graph_version == version and record.candidate.state["completedStepIds"] == ["A"]
        assert record.identity_link.retained_attempt_ids == (node.attempt_id,)
        issued = rt.issue_execution_permit(result.handoff_id, idempotency_key="native-history-permit-" + str(version))
        assert issued.status == "ISSUED", issued
        assert rt.execution_value_store.list_node_commits(run_id=run_id) == receipts
        assert retained_node(rt, run_id, node.operation_id) == node
        assert rt.identity_lifecycle.repositories.attempts.get(node.attempt_id).status.value == "cancelled"
        assert agent.calls == ["A"]
        if version == 2:
            assert asyncio.run(rt.execute_prepared_run(run_id)).status == WorkflowStatus.WAITING_REVIEW


def retain_noninvoked_failure(rt, workflow, agent, run_id, permit, *, step_id="C"):
    """Seed the persisted cut after a failed operation and current-run retry.

    Use real Identity repositories and the execution WAL, without replacing any
    handoff, replay-safety or graph-acceptance verifier.
    """
    run = workflow.get_run(run_id)
    repos = rt.identity_lifecycle.repositories
    identity = repos.runs.get(run_id)
    task_id = repos.task_bindings.find_for_acg_node(step_id, identity.blueprint_id)[0].task_id
    attempt = Attempt(runId=run_id, taskId=task_id, attemptNumber=1, status="failed")
    repos.attempts.add(attempt)
    repos.step_executions.add(StepExecution(runId=run_id, taskId=task_id,
        attemptId=attempt.attempt_id, status="failed"))
    repos.execution_bindings.add(ExecutionBinding(attemptId=attempt.attempt_id,
        acgNodeId=step_id, resourceId="runner", agentId="runner", modelId="none"))
    operation = ACGNodeRunner._commit_id(run_id, step_id, 0, execution_generation=permit.attempt_generation)
    rt.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=operation)
    prepared = NodeExecutionRecord(operationId=operation,
        executionInstanceId=f"{permit.attempt_generation}:{run_id}:{step_id}:0:root",
        runId=run_id, stepId=step_id, attemptId=attempt.attempt_id, phase="prepared")
    rt.execution_value_store.transition_node_execution(prepared)
    rt.execution_value_store.transition_node_execution(prepared.model_copy(update={
        "phase": NodeExecutionPhase.FAILED, "failure_code": "AGENT_NOT_IN_SCOPE"}))
    step = run.get_step(step_id)
    step.attempt = step.retry_count = 1
    workflow.save_run(run)


def retained_node(rt, run_id, operation):
    row = rt.execution_value_store._connection.execute(
        "SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
        (run_id, operation)).fetchone()
    return NodeExecutionRecord.model_validate_json(row[0])


def test_retained_failure_survives_repeated_graph_handoffs_and_never_counts_as_completed(ready_handoff):
    def failed_before_success(*args):
        retain_noninvoked_failure(*args, step_id="B")

    rt, workflow, agent, run_id, activation_id, ledger, _, old_permit = next_activation(
        ready_handoff, before_execute=failed_before_success)
    receipts = rt.execution_value_store.list_node_commits(run_id=run_id)
    failed = next(item for item in receipts if item["stage"] != "committed")
    failure = retained_node(rt, run_id, failed["commitId"])
    for key, act, version in (("retained-third", activation_id, 3), ("retained-fourth", None, 4)):
        if act is None:
            paused = asyncio.run(rt.execute_prepared_run(run_id))
            assert paused.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A", "B"]
            act = activate_next_graph(rt, paused, key="generation-four", node="F", predecessor="E")
        before = workflow.get_run(run_id)
        handoff = rt.prepare_graph_handoff(act, idempotency_key=key)
        assert handoff.status == "STATE_PREPARED", handoff
        record = ledger.get_handoff(handoff.handoff_id)
        assert record.graph_version == version
        assert record.candidate.state["completedStepIds"] == ["A", "B"]
        assert record.candidate.state["outputRefs"] == before.execution_state["outputRefs"]
        assert record.identity_link.retained_attempt_ids == (failure.attempt_id,)
        assert failure.attempt_id not in record.identity_link.prefix_attempt_ids
        assert workflow.get_run(run_id) == before
        issued = rt.issue_execution_permit(handoff.handoff_id, idempotency_key=key + "-permit")
        assert issued.status == "ISSUED", issued
        resumed = workflow.get_run(run_id)
        assert resumed.execution_state["executionGeneration"] != old_permit.attempt_generation
        assert resumed.get_step("B").attempt == resumed.get_step("B").retry_count == 1
        assert resumed.completed_step_ids == ["A", "B"]
        assert rt.execution_value_store.list_node_commits(run_id=run_id) == receipts
        assert rt.identity_lifecycle.repositories.attempts.get(failure.attempt_id).status.value == "failed"
        assert agent.calls == ["A", "B"]


@pytest.mark.parametrize("effect", ["unknown", "write"])
def test_activation_reuses_replay_proof_and_rejects_unknown_or_write_activity(ready_handoff, effect):
    rt, workflow, agent, run_id, materialization_id, _, _, _ = next_activation(
        ready_handoff, before_execute=retain_noninvoked_failure, materialize_only=True)
    receipt = next(item for item in rt.execution_value_store.list_node_commits(run_id=run_id)
                   if item["stage"] != "committed")
    node = retained_node(rt, run_id, receipt["commitId"])
    changed = node.model_copy(update={"phase": NodeExecutionPhase.PREPARED, "failure_code": None})
    with rt.execution_value_store._connection as conn:
        conn.execute("UPDATE acg_node_executions SET phase='prepared',payload_json=? WHERE operation_id=?",
                     (changed.model_dump_json(by_alias=True), node.operation_id))
    if effect == "write":
        rt.execution_value_store.put_tool_value(run_id=run_id, step_id="C",
            key=node.operation_id + ":tools:0:call:0:request", payload={
                "request": {"invocationId": node.operation_id + ":tools:0:call:0", "capabilityId": "fs.write"},
                "identity": {"commitId": node.operation_id}})
    before = workflow.get_run(run_id)
    for _ in range(2):
        result = rt.prepare_graph_activation(materialization_id, idempotency_key="unsafe-history")
        assert result.status == "REJECTED" and result.code.value == "CONTROL_BARRIER_BLOCKED", result
        assert rt.graph_activation_authority.store.activation_for(materialization_id) is None
        assert workflow.get_run(run_id) == before and agent.calls == ["A", "B"]


@pytest.mark.parametrize("damage", ["unknown_attempt", "wrong_counter", "wrong_generation", "unknown_effect"])
def test_retained_history_still_rejects_unexplained_execution_facts(ready_handoff, damage):
    rt, workflow, agent, run_id, activation, ledger, _, _ = next_activation(
        ready_handoff, before_execute=retain_noninvoked_failure)
    repos = rt.identity_lifecycle.repositories
    run = workflow.get_run(run_id)
    failed = next(item for item in rt.execution_value_store.list_node_commits(run_id=run_id) if item["stage"] != "committed")
    node = retained_node(rt, run_id, failed["commitId"])
    if damage == "unknown_attempt":
        previous = repos.attempts.get(node.attempt_id)
        repos.attempts.add(Attempt(runId=run_id, taskId=previous.task_id, attemptNumber=2, status="failed"))
    elif damage == "wrong_counter":
        run.get_step("C").attempt = run.get_step("C").retry_count = 0
        with workflow._connect() as conn:
            conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run_id))
    else:
        changed = node.model_copy(update={"execution_instance_id": "forged:" + node.execution_instance_id}
            if damage == "wrong_generation" else {"failure_code": "UNKNOWN_EFFECT"})
        with rt.execution_value_store._connection as conn:
            conn.execute("UPDATE acg_node_executions SET payload_json=? WHERE operation_id=?",
                         (changed.model_dump_json(by_alias=True), node.operation_id))
    before = workflow.get_run(run_id)
    result = rt.prepare_graph_handoff(activation, idempotency_key="invalid-history")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(activation) is None
    assert workflow.get_run(run_id) == before and agent.calls == ["A", "B"]
