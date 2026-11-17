"""A rejected continuation cannot overwrite a newer or terminal Run."""
from threading import RLock
from types import SimpleNamespace

import pytest

from contracts.workflow import RuntimeRunRecord, WorkflowStatus
from runtime.workspace_review_execution import WorkspaceReviewContinuation
from support.run_execution_fence import RunFenceBusy, acquire_run_fence


def _blocked_workspace_run(**overrides):
    """Small projection-only fixture for legacy blocked continuations."""
    execution_state = {
        "graphId": "graph",
        "graphVersion": 1,
        "workspaceObservations": [{"path": "."}],
        "workspaceReviewContinuation": {
            "observationId": "observation:1",
            "sourceGraphVersion": 1,
            "blocked": True,
            "errorType": "_TransitionRejected",
            # Older rows omitted errorCode. The parser must recover it from
            # the bounded authority diagnostic, without trusting model text.
            "reason": "Workspace review graph transition rejected: INVALID_PROPOSAL: started or settled work cannot be changed",
        },
        "planningLoop": {"current": {"observationId": "observation:1"}},
        "reviewPayload": {"subjectType": "planner", "subjectId": "graph", "observationId": "observation:1"},
        "graphActivation": {"executionPermit": {"permitId": "permit"}},
    }
    execution_state.update(overrides.pop("executionState", {}))
    return SimpleNamespace(
        run_id="run", status=WorkflowStatus.WAITING_REVIEW, review_mode="auto",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}},
        execution_state=execution_state, **overrides,
    )


def test_legacy_blocked_continuation_is_replanable_without_error_code():
    continuation = WorkspaceReviewContinuation(SimpleNamespace())
    assert continuation.can_replan(_blocked_workspace_run()) is True


@pytest.mark.parametrize("change", [
    {"reviewPayload": {"subjectType": "node", "subjectId": "A", "observationId": "observation:1"}},
    {"reviewPayload": {"subjectType": "planner", "subjectId": "graph", "observationId": "other"}},
    {"graphVersion": 2},
    {"workspaceReviewContinuation": {"observationId": "observation:1", "sourceGraphVersion": 2,
        "blocked": True, "errorType": "_TransitionRejected",
        "reason": "Workspace review graph transition rejected: INVALID_PROPOSAL: stale"}},
])
def test_blocked_continuation_requires_current_planner_observation_and_graph(change):
    continuation = WorkspaceReviewContinuation(SimpleNamespace())
    assert continuation.can_replan(_blocked_workspace_run(executionState=change)) is False


@pytest.mark.parametrize("defect,expected_error", [
    ("revoked_access", "write access revoked"),
    ("unknown_write", "unsettled write operation"),
    ("subject", "does not own the current review barrier"),
    ("observation", "does not own the current review barrier"),
    ("graph", "does not own the current review barrier"),
    ("checkpoint_body", "differs from its native checkpoint"),
    ("latest_head", "unrelated checkpoint head"),
])
def test_replan_guards_leave_run_and_checkpoint_unchanged(tmp_path, monkeypatch, defect, expected_error):
    from copy import deepcopy

    from components.executor import ACGExecutionState
    import runtime.permit_recovery as recovery

    run = RuntimeRunRecord(missionId="mission", workflowId="flow", domain="general", runtimeEngine="acg",
        status=WorkflowStatus.WAITING_REVIEW, reviewMode="auto",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}})
    state = ACGExecutionState(runId=run.run_id, graphId="graph", graphVersion=1,
        checkpointId="checkpoint", executionPermitId="permit", executionGeneration="generation",
        reviewPayload={"subjectType": "planner", "subjectId": "graph", "observationId": "observation:1"})
    pending = {"observationId": "observation:1", "sourceGraphVersion": 1, "patch": {}}
    run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
    run.execution_state.update(workspaceObservations=[{"path": "."}], workspaceReviewContinuation=pending,
        graphActivation={"executionPermit": {"permitId": "permit"}})
    checkpoint = state.model_dump(by_alias=True, mode="json")
    latest = (state.checkpoint_id, deepcopy(checkpoint))
    if defect in {"subject", "observation"}:
        field, value = ("subjectType", "node") if defect == "subject" else ("observationId", "other")
        run.execution_state["reviewPayload"][field] = value
    elif defect == "graph":
        pending["sourceGraphVersion"] = 2
    elif defect == "checkpoint_body":
        checkpoint["graphVersion"] = 2
    elif defect == "latest_head":
        latest = ("other-checkpoint", {**checkpoint, "checkpointId": "other-checkpoint", "outputSummaries": {"A": "unacknowledged work"}})

    durable = {"run": run.model_copy(deep=True), "checkpoint": deepcopy(checkpoint), "latest": deepcopy(latest)}
    before = deepcopy(durable)
    writes = []

    def no_write(*args, **kwargs):
        writes.append((args, kwargs))
        pytest.fail("a rejected replan must not write the Run or a new checkpoint")

    def require_access(*_):
        if defect == "revoked_access":
            raise PermissionError("write access revoked")

    def replay_safe(*_):
        if defect == "unknown_write":
            raise ValueError("unsettled write operation")

    def prepare_feedback(current, current_state, **_):
        # This collaborator has its own tests. Here its valid cleared state
        # lets us exercise the later checkpoint-head guard in isolation.
        current_state.review_payload = None

    monkeypatch.setattr(recovery, "assert_replay_safe_operations", replay_safe)
    runtime = SimpleNamespace(
        workflow_store=SimpleNamespace(db_path=tmp_path / "workflow.sqlite3",
            get_run=lambda _: durable["run"].model_copy(deep=True), save_run=no_write),
        checkpoint_store=SimpleNamespace(load=lambda **_: deepcopy(durable["checkpoint"]),
            load_latest=lambda **_: deepcopy(durable["latest"])),
        run_lock_manager=SimpleNamespace(lock_for=lambda _: RLock()),
        _run_cancellation_requested=lambda _: False,
        semantic_principal_provider=lambda: object(),
        mission_semantic_service=SimpleNamespace(require_write_access=require_access),
        _validate_acg_state_references=lambda **_: None,
        prepare_planning_commit_rejection_feedback=prepare_feedback,
        acg_state_persistence=SimpleNamespace(save_checkpoint=no_write),
    )
    continuation = WorkspaceReviewContinuation(runtime)
    with pytest.raises((PermissionError, ValueError), match=expected_error):
        continuation._prepare_replan(run, pending, code="INVALID_PROPOSAL", reason="repair the semantic proposal")
    assert durable == before and not writes


@pytest.mark.parametrize("race", ["none", "pending", "cancelled", "superseded"])
def test_rejection_persistence_checks_fence_snapshot_and_proposal(tmp_path, monkeypatch, race):
    run = RuntimeRunRecord(missionId="mission", workflowId="flow", domain="general", runtimeEngine="acg",
        status=WorkflowStatus.WAITING_REVIEW, reviewMode="auto",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}},
        executionState={"graphVersion": 1, "workspaceObservations": [{"path": "."}],
            "workspaceReviewContinuation": {"observationId": "first", "sourceGraphVersion": 1}})
    durable = {"run": run.model_copy(deep=True), "writes": 0}
    db_path = tmp_path / "workflow.sqlite3"
    def save(current, *, expected_snapshot):
        assert expected_snapshot == durable["run"]
        with pytest.raises(RunFenceBusy):
            acquire_run_fence(db_path, run.run_id)
        durable.update(run=current.model_copy(deep=True), writes=durable["writes"] + 1)
    store = SimpleNamespace(db_path=db_path, get_run=lambda _: durable["run"].model_copy(deep=True),
                            save_run=save, list_planning_inputs=lambda _: [])
    rt = SimpleNamespace(workflow_store=store, run_lock_manager=SimpleNamespace(lock_for=lambda _: RLock()),
        planning_commit_authority=object(), graph_materialization_authority=object(),
        graph_activation_authority=object(), graph_handoff_authority=object(), execution_permit_authority=object())
    continuation = WorkspaceReviewContinuation(rt)
    diagnostics = []
    monkeypatch.setattr(continuation, "_publish_status", lambda *args: diagnostics.append(args))
    def reject(*_):
        if race == "pending":
            durable["run"].execution_state["workspaceReviewContinuation"]["observationId"] = "newer"
        elif race != "none":
            durable["run"].status = WorkflowStatus(race)
        raise ValueError("authority denied")
    monkeypatch.setattr(continuation, "_advance", reject)
    assert continuation.resume(run) is None
    assert durable["writes"] == (1 if race == "none" else 0)
    if race == "none":
        assert durable["run"].execution_state["workspaceReviewContinuation"]["blocked"]
        assert diagnostics == [(run.run_id, "blocked", "ValueError")]
    else:
        assert not durable["run"].execution_state["workspaceReviewContinuation"].get("blocked")
        assert not diagnostics


def test_paused_handoff_rejection_publishes_actual_authority_reason_without_writing_frozen_run(tmp_path, monkeypatch, caplog):
    from runtime.workspace_review_execution import _TransitionRejected

    run = RuntimeRunRecord(missionId="mission", workflowId="flow", domain="general", runtimeEngine="acg",
        status=WorkflowStatus.RETRYING, reviewMode="auto",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}},
        executionState={"graphVersion": 2, "workspaceObservations": [{"path": "."}],
            "workspaceReviewContinuation": {"observationId": "observation:1", "sourceGraphVersion": 1},
            "graphActivation": {"activationId": "activation:2", "executionPermit": None}})
    before = run.model_copy(deep=True)
    writes, diagnostics = [], []
    rt = SimpleNamespace(workflow_store=SimpleNamespace(db_path=tmp_path / "workflow.sqlite3",
            get_run=lambda _: before.model_copy(deep=True), list_planning_inputs=lambda _: [],
            save_run=lambda *a, **kw: writes.append((a, kw))),
        run_lock_manager=SimpleNamespace(lock_for=lambda _: RLock()), planning_commit_authority=object(),
        graph_materialization_authority=object(), graph_activation_authority=object(),
        graph_handoff_authority=object(), execution_permit_authority=object())
    continuation = WorkspaceReviewContinuation(rt)
    monkeypatch.setattr(continuation, "_publish_status", lambda *args, **kwargs: diagnostics.append((args, kwargs)))
    rejection = SimpleNamespace(code="INVALID_PROPOSAL", reason="current origin differs from accepted frozen provenance")

    def rejected(*_):
        raise _TransitionRejected(rejection)

    monkeypatch.setattr(continuation, "_advance", rejected)
    assert continuation.resume(run) is None
    assert not writes and run == before
    assert diagnostics == [((run.run_id, "blocked", "INVALID_PROPOSAL"), {"diagnostics": {
        "activationId": "activation:2", "observationId": "observation:1", "graphVersion": 2,
        "errorType": "_TransitionRejected", "authorityReason": rejection.reason}})]
    assert rejection.reason in caplog.text and "activation:2" in caplog.text
    assert continuation.resume(run) is None and len(diagnostics) == 1


@pytest.mark.parametrize("lost_ack", [False, True])
def test_rejection_feedback_advances_checkpoint_head_when_cleared_body_already_exists(tmp_path, monkeypatch, lost_ack):
    from components.executor import ACGExecutionState
    from components.mission_manager.state_machine import StateMachine
    from components.recovery.checkpoint import ACGCheckpointStore
    from runtime.state_persistence import ACGStatePersistenceService

    run = RuntimeRunRecord(missionId="mission", workflowId="flow", domain="general", runtimeEngine="acg",
        status=WorkflowStatus.WAITING_REVIEW, reviewMode="auto",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}})
    durable = {"run": run}

    def save(current, *, expected_snapshot):
        assert expected_snapshot == durable["run"]
        durable["run"] = current.model_copy(deep=True)

    store = SimpleNamespace(db_path=tmp_path / "workflow.sqlite3",
        get_run=lambda _: durable["run"].model_copy(deep=True), save_run=save)
    checkpoints = ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3")
    persistence = ACGStatePersistenceService(collaborators=SimpleNamespace(
        workflow_store=store, checkpoint_store=checkpoints))
    state = ACGExecutionState(runId=run.run_id, graphId="graph")
    historical_id = persistence.save_checkpoint(run, state)
    state.review_payload = {"subjectType": "planner", "subjectId": "graph", "observationId": "observation:1"}
    persistence.save_checkpoint(run, state)
    pending = {"observationId": "observation:1", "sourceGraphVersion": 1, "patch": {}}
    run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
    run.execution_state.update(workspaceObservations=[{"path": "."}], workspaceReviewContinuation=pending)
    version = checkpoints.latest_version(run_id=run.run_id)

    def prepare_feedback(current, current_state, **_):
        current_state.review_payload = None
        current.execution_state.pop("workspaceReviewContinuation")

    runtime = SimpleNamespace(workflow_store=store, checkpoint_store=checkpoints,
        run_lock_manager=SimpleNamespace(lock_for=lambda _: RLock()),
        _run_cancellation_requested=lambda _: False, semantic_principal_provider=lambda: object(),
        mission_semantic_service=SimpleNamespace(require_write_access=lambda *_: None),
        _validate_acg_state_references=lambda **_: None,
        prepare_planning_commit_rejection_feedback=prepare_feedback,
        acg_state_persistence=persistence, state_machine=StateMachine())
    continuation = WorkspaceReviewContinuation(runtime)
    monkeypatch.setattr(continuation, "_publish_status", lambda *_: None)

    class LostCheckpointAck(BaseException):
        pass

    if lost_ack:
        def interrupt():
            raise LostCheckpointAck()

        persistence.after_checkpoint_hook = interrupt
        with pytest.raises(LostCheckpointAck):
            continuation._prepare_replan(run, pending, code="INVALID_PROPOSAL", reason="repair proposal")
        assert durable["run"].status == WorkflowStatus.WAITING_REVIEW
        persistence.after_checkpoint_hook = None

    prepared = continuation._prepare_replan(run, pending, code="INVALID_PROPOSAL", reason="repair proposal")
    head, body = checkpoints.load_latest(run_id=run.run_id)
    assert prepared.status == WorkflowStatus.RETRYING
    assert head == prepared.execution_state["checkpointId"] != historical_id
    assert body["reviewPayload"] is None
    assert checkpoints.latest_version(run_id=run.run_id) == version + 1
