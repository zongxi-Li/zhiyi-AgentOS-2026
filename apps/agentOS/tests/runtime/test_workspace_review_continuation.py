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


@pytest.mark.parametrize("head", [None, "graph:active", "semantic:next", "graph:next"])
def test_only_the_active_commitment_can_reenter_the_ordinary_planner(head):
    run = _blocked_workspace_run(mission_id="mission")
    run.execution_state["graphActivation"]["sourceCommitId"] = "graph:active"
    ledger = SimpleNamespace(latest=lambda _: SimpleNamespace(commit_id=head) if head else None)
    continuation = WorkspaceReviewContinuation(SimpleNamespace(
        planning_commit_authority=SimpleNamespace(store=ledger)))
    assert continuation.can_replan(run) is (head in {None, "graph:active"})


@pytest.mark.parametrize("head", ["semantic:next", "graph:next"])
def test_accepted_revision_rejection_preserves_the_execution_barrier(tmp_path, monkeypatch, head):
    from runtime.workspace_review_execution import _TransitionRejected

    run = RuntimeRunRecord(missionId="mission", workflowId="flow", domain="general", runtimeEngine="acg",
        status=WorkflowStatus.WAITING_REVIEW, reviewMode="auto",
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}},
        executionState={
            "graphId": "graph", "graphVersion": 1, "checkpointId": "checkpoint:active",
            "executionPermitId": "permit:active", "workspaceObservations": [{"path": "."}],
            "workspaceReviewContinuation": {"observationId": "observation:1", "sourceGraphVersion": 1,
                                             "patch": {"metadata": {"workspaceScope": {"version": 1}}}},
            "planningLoop": {"current": {"observationId": "observation:1"}},
            "reviewPayload": {"subjectType": "planner", "subjectId": "graph", "observationId": "observation:1"},
            "graphActivation": {"sourceCommitId": "graph:active", "executionPermit": {"permitId": "permit:active"}},
        })
    durable = {"run": run.model_copy(deep=True), "head": "graph:active", "writes": 0}

    def save(current, *, expected_snapshot):
        assert expected_snapshot == durable["run"]
        assert current.status == WorkflowStatus.WAITING_REVIEW
        durable.update(run=current.model_copy(deep=True), writes=durable["writes"] + 1)

    def no_execution(*_, **__):
        pytest.fail("an accepted but inactive revision must not retry the old graph")

    runtime = SimpleNamespace(
        workflow_store=SimpleNamespace(db_path=tmp_path / "workflow.sqlite3",
            get_run=lambda _: durable["run"].model_copy(deep=True), save_run=save,
            list_planning_inputs=lambda _: []),
        run_lock_manager=SimpleNamespace(lock_for=lambda _: RLock()),
        _run_cancellation_requested=lambda _: False,
        planning_commit_authority=SimpleNamespace(store=SimpleNamespace(
            latest=lambda _: SimpleNamespace(commit_id=durable["head"]))),
        graph_materialization_authority=object(), graph_activation_authority=object(),
        graph_handoff_authority=object(), execution_permit_authority=object(),
        prepare_planning_commit_rejection_feedback=no_execution,
        acg_state_persistence=SimpleNamespace(save_checkpoint=no_execution),
    )
    continuation = WorkspaceReviewContinuation(runtime)
    events = []
    monkeypatch.setattr(continuation, "_publish_status", lambda *args: events.append(args))
    reason = "the accepted revision cannot preserve the frozen execution prefix"

    def reject_after_acceptance(*_):
        durable["head"] = head
        raise _TransitionRejected(SimpleNamespace(code="INVALID_PROPOSAL", reason=reason))

    monkeypatch.setattr(continuation, "_advance", reject_after_acceptance)
    assert continuation.resume(run) is None
    held = durable["run"]
    pending = held.execution_state["workspaceReviewContinuation"]
    assert pending["blocked"] and pending["errorCode"] == "INVALID_PROPOSAL"
    assert pending["errorType"] == "_TransitionRejected" and reason in pending["reason"]
    assert held.execution_state["reviewPayload"] == run.execution_state["reviewPayload"]
    assert held.execution_state["checkpointId"] == "checkpoint:active"
    assert held.execution_state["executionPermitId"] == "permit:active"
    assert not held.execution_state.get("planningCommitRejection")
    assert durable["writes"] == 1
    assert events == [(run.run_id, "blocked", "INVALID_PROPOSAL")]
    assert not continuation.can_replan(held)
    monkeypatch.setattr(continuation, "_advance", no_execution)
    assert continuation.resume(held) is None and durable["writes"] == 1
    # The head is checked again under the Run fence, even if an earlier wake
    # observed a current graph. No checkpoint or RETRYING projection is made.
    assert continuation._prepare_replan(held, pending, code="INVALID_PROPOSAL", reason=reason) is None
    assert durable["writes"] == 1


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


@pytest.mark.parametrize("change", [
    {},
    {"blocked": False},
    {"observationId": ""},
    {"observationId": "stale", "sourceGraphVersion": 2},
    {"observationId": "stale", "sourceGraphVersion": 0},
    {"observationId": "stale", "sourceGraphVersion": True},
])
def test_retirement_never_removes_current_live_or_unowned_proposal(change):
    from copy import deepcopy
    from runtime.workspace_review_execution import retire_stale_workspace_continuation

    run = _blocked_workspace_run()
    run.execution_state["workspaceReviewContinuation"].update(change)
    before = deepcopy(run.execution_state)
    store = SimpleNamespace(put_graph_patch=lambda **_: pytest.fail("must not archive this proposal"))
    assert retire_stale_workspace_continuation(run, value_store=store,
        step_id="graph", operation_id="current-wake") is None
    assert run.execution_state == before


def test_retirement_storage_failure_preserves_original_live_pointer():
    from copy import deepcopy
    from runtime.workspace_review_execution import retire_stale_workspace_continuation

    run = _blocked_workspace_run()
    run.execution_state["workspaceReviewContinuation"]["observationId"] = "superseded-observation"
    before = deepcopy(run.execution_state)

    def unavailable(**kwargs):
        raise OSError("archive storage unavailable")

    with pytest.raises(OSError, match="archive storage unavailable"):
        retire_stale_workspace_continuation(run, value_store=SimpleNamespace(put_graph_patch=unavailable),
            step_id="graph", operation_id="current-wake")
    assert run.execution_state == before


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
    from components.executor.value_store import InMemoryExecutionValueStore
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
    reason = "  " + "repair proposal " * 100 + "  "

    def prepare_feedback(current, current_state, **feedback):
        current_state.review_payload = None
        current.execution_state.pop("workspaceReviewContinuation")
        current.execution_state["planningCommitRejection"] = {
            "observationId": feedback["source_observation_id"],
            "code": feedback["code"].strip()[:128], "reason": feedback["reason"].strip()[:800],
            "proposalRef": feedback["proposal_ref"],
        }

    runtime = SimpleNamespace(workflow_store=store, checkpoint_store=checkpoints,
        run_lock_manager=SimpleNamespace(lock_for=lambda _: RLock()),
        _run_cancellation_requested=lambda _: False, semantic_principal_provider=lambda: object(),
        mission_semantic_service=SimpleNamespace(require_write_access=lambda *_: None),
        _validate_acg_state_references=lambda **_: None,
        prepare_planning_commit_rejection_feedback=prepare_feedback,
        execution_value_store=InMemoryExecutionValueStore(),
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
            continuation._prepare_replan(run, pending, code="INVALID_PROPOSAL", reason=reason)
        assert durable["run"].status == WorkflowStatus.WAITING_REVIEW
        persistence.after_checkpoint_hook = None

    prepared = continuation._prepare_replan(run, pending, code="INVALID_PROPOSAL", reason=reason)
    feedback = prepared.execution_state["planningCommitRejection"]
    archived = runtime.execution_value_store.get_graph_patch(run_id=run.run_id, patch_ref=feedback["proposalRef"])
    assert archived["rejection"] == {"code": "INVALID_PROPOSAL", "reason": reason.strip()[:800]}
    head, body = checkpoints.load_latest(run_id=run.run_id)
    assert prepared.status == WorkflowStatus.RETRYING
    assert head == prepared.execution_state["checkpointId"] != historical_id
    assert body["reviewPayload"] is None
    assert checkpoints.latest_version(run_id=run.run_id) == version + 1
