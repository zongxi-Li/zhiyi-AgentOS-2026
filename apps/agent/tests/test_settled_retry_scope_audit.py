"""Independent checks of explicit recovery authorization and Planner barriers."""
from types import SimpleNamespace

import pytest

from contracts.local_runtime import LocalRuntimeAuthorizationRef
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, StepStatus, WorkflowStatus, WorkflowStep
from runtime.orchestration.permit_recovery import is_failed_planner_recovery, operator_recovery_authorization
from support.stores.memory_workflow_store import MemoryWorkflowStore


@pytest.fixture
def recovery_scope():
    store = MemoryWorkflowStore()
    store.save_mission(RuntimeMissionRecord(missionId="mission", title="review"))
    scope = {"workspaceId": "workspace", "grantId": "grant", "resourceId": "hands"}
    actor = SimpleNamespace(actor_id="operator", tenant_id="tenant")
    run = RuntimeRunRecord(runId="run", missionId="mission", workflowId="workflow", domain="general",
        runtimeEngine="acg", status=WorkflowStatus.FAILED, input={"workspaceBinding": dict(scope)},
        steps=[WorkflowStep(stepId="review", name="review", agentName="native", status="failed")])
    services = SimpleNamespace(workflow_store=store,
        local_runtime_resource=SimpleNamespace(profile=SimpleNamespace(runtime_id="hands")),
        local_runtime_authorization=LocalRuntimeAuthorizationRef(workspaceId="workspace", grantId="grant"),
        semantic_principal_provider=lambda: actor)
    return SimpleNamespace(store=store, scope=scope, actor=actor, run=run, services=services)


def enable(s):
    return s.store.set_task_operator_policy("mission", permission="task_collaboration", approval_mode="full",
        workspace_scope=s.scope, actor={"userId": "policy-owner", "tenantId": "tenant"},
        operation_id="enable", expected_policy_revision=0)


def test_default_ask_never_manufactures_settled_session_authorization(recovery_scope):
    s = recovery_scope
    assert operator_recovery_authorization(s.services, s.run, "review", "recover", "fingerprint") is None


def test_explicit_settled_retry_binds_current_policy_and_current_operator(recovery_scope):
    s = recovery_scope
    enable(s)
    decision = operator_recovery_authorization(s.services, s.run, "review", "recover", "fingerprint")
    assert decision == {"intent": "recover", "operationId": "recover", "requestFingerprint": "fingerprint",
        "missionId": "mission", "runId": "run", "stepId": "review", "policyRevision": 1,
        "actor": {"userId": "operator", "tenantId": "tenant"}, "workspaceScope": s.scope,
        "mayRepeatSettledActions": True}


@pytest.mark.parametrize("key", ["workspaceId", "grantId", "resourceId"])
def test_policy_does_not_authorize_an_expanded_workspace_scope(recovery_scope, key):
    s = recovery_scope
    enable(s)
    s.run.input["workspaceBinding"][key] = "replacement"
    assert operator_recovery_authorization(s.services, s.run, "review", "recover", "fingerprint") is None


@pytest.mark.parametrize("defect", ["missing_actor", "missing_operation", "missing_fingerprint", "grant", "revoked"])
def test_full_policy_still_requires_real_operator_and_live_workspace_authority(recovery_scope, defect):
    s = recovery_scope
    enable(s)
    operation, fingerprint = "recover", "fingerprint"
    if defect == "missing_actor": s.services.semantic_principal_provider = lambda: None
    elif defect == "missing_operation": operation = ""
    elif defect == "missing_fingerprint": fingerprint = ""
    elif defect == "grant":
        s.services.local_runtime_authorization = LocalRuntimeAuthorizationRef(workspaceId="workspace", grantId="replacement")
    elif defect == "revoked":
        def revoked(_): raise PermissionError("grant revoked")
        s.services.workspace_authority = SimpleNamespace(resolve=revoked)
    with pytest.raises((ValueError, PermissionError)):
        operator_recovery_authorization(s.services, s.run, "review", operation, fingerprint)


def test_policy_revocation_prevents_creating_another_explicit_settled_retry(recovery_scope):
    s = recovery_scope
    enable(s)
    s.store.set_task_operator_policy("mission", permission="task_collaboration", approval_mode="ask",
        actor={"userId": "operator", "tenantId": "tenant"}, operation_id="revoke", expected_policy_revision=1)
    assert operator_recovery_authorization(s.services, s.run, "review", "recover", "fingerprint") is None


def planner_barrier(s):
    run = s.run.model_copy(deep=True)
    run.status = WorkflowStatus.WAITING_REVIEW
    run.execution_state = {"reviewPayload": {"subjectType": "planner"},
        "planningLoop": {"current": {"decision": {"action": "wait"}}}}
    return run


def test_idle_planner_wait_can_offer_explicit_recovery_of_the_single_failed_node(recovery_scope):
    assert is_failed_planner_recovery(planner_barrier(recovery_scope)) is True


@pytest.mark.parametrize("step_status", [StepStatus.FAILED, StepStatus.CANCELLED])
def test_failed_run_can_replace_its_idle_planner_marker_without_relabeling_history(recovery_scope, step_status):
    run = planner_barrier(recovery_scope)
    run.status = WorkflowStatus.FAILED
    run.get_step("review").status = step_status
    review = run.execution_state["reviewPayload"]
    review.update(observationId="same-observation", reasonCode="PLANNER_WAIT", question=None)
    current = run.execution_state["planningLoop"]["current"]
    current.update(observationId="same-observation", status="applied")
    current["decision"].update(observationId="same-observation", waitFor=None, question=None)
    before = run.model_dump(by_alias=True, mode="json")
    assert is_failed_planner_recovery(run) is True
    assert run.model_dump(by_alias=True, mode="json") == before
    assert run.get_step("review").status == step_status
    assert not any(event.payload.get("decision") == "rejected" for event in run.trace)


def test_waiting_planner_with_only_cancelled_steps_keeps_its_existing_pause(recovery_scope):
    run = planner_barrier(recovery_scope)
    run.get_step("review").status = StepStatus.CANCELLED
    assert is_failed_planner_recovery(run) is False


@pytest.mark.parametrize("run_status", [WorkflowStatus.WAITING_REVIEW, WorkflowStatus.FAILED])
@pytest.mark.parametrize("defect", ["question", "marker_question", "condition", "armed_wait", "step_review",
    "node_review", "control_review", "active_run", "active_state", "no_failed", "cancelled"])
def test_operator_recovery_cannot_skip_a_fact_question_or_node_control_review(recovery_scope, defect, run_status):
    run = planner_barrier(recovery_scope)
    run.status = run_status
    if run_status is WorkflowStatus.FAILED:
        run.get_step("review").status = StepStatus.CANCELLED
    if defect == "question":
        run.execution_state["planningLoop"]["current"]["decision"]["question"] = {"prompt": "confirm facts"}
    elif defect == "marker_question":
        run.execution_state["reviewPayload"]["question"] = {"prompt": "confirm facts"}
    elif defect == "condition":
        run.execution_state["planningLoop"]["current"]["decision"]["waitFor"] = {"kind": "node_available", "nodeId": "node"}
    elif defect == "armed_wait":
        run.execution_state["planningLoop"]["waiting"] = {"observationId": "current", "condition": {"kind": "node_available", "nodeId": "node"}}
    elif defect == "step_review":
        run.steps.append(run.get_step("review").model_copy(update={"step_id": "node-review", "status": StepStatus.WAITING_REVIEW}))
    elif defect in {"node_review", "control_review"}:
        run.execution_state["reviewPayload"]["subjectType"] = "step" if defect == "node_review" else "control"
    elif defect == "active_run": run.active_step_ids = ["review"]
    elif defect == "active_state": run.execution_state["activeStepIds"] = ["review"]
    elif defect == "no_failed": run.steps = []
    elif defect == "cancelled": run.status = WorkflowStatus.CANCELLED
    assert is_failed_planner_recovery(run) is False


def test_idle_planner_can_recover_multiple_interrupted_nodes_with_exact_scope(recovery_scope):
    s = recovery_scope
    enable(s)
    s.run = planner_barrier(s)
    s.run.steps.extend([
        s.run.steps[0].model_copy(update={"step_id": "sibling"}),
        s.run.steps[0].model_copy(update={"step_id": "cancelled-sibling", "status": type(s.run.steps[0].status).CANCELLED}),
        s.run.steps[0].model_copy(update={"step_id": "completed", "status": type(s.run.steps[0].status).COMPLETED}),
        s.run.steps[0].model_copy(update={"step_id": "pending", "status": type(s.run.steps[0].status).PENDING}),
    ])
    s.run.completed_step_ids = ["completed"]
    assert is_failed_planner_recovery(s.run) is True
    auth = operator_recovery_authorization(s.services, s.run, "review", "recover", "hash")
    assert auth["stepId"] == "review"
    assert auth["stepIds"] == ["review", "sibling", "cancelled-sibling"]
    with pytest.raises(ValueError, match="anchor"):
        operator_recovery_authorization(s.services, s.run, "completed", "recover", "hash")
