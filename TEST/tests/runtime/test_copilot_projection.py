import json
from types import SimpleNamespace

from components.executor.value_store import SQLiteExecutionValueStore
from contracts.planning import TaskPlan, PlannedTask
from runtime.projections.copilot_projection import initial_plan_summary, planning_progress, review_summary
from contracts.workflow import WorkflowStatus, utc_now


def sources():
    plan = TaskPlan(missionId="mission_0123456789ab", nodes=(PlannedTask(key="T1", title="核对事实", objective="确认来源",
        decompositionRationale="先核对事实，避免后续分析依赖假设", constraints=[{"value": "不修改文件"}],
        acceptanceCriteria=("标明来源",), producedArtifacts=("分析报告",)),), expectedArtifacts=("分析报告",))
    run = SimpleNamespace(run_id="run", mission_id="mission_0123456789ab", input={"taskGoal": "分析故障", "apiKey": "private"},
        execution_state={"taskPlan": plan.model_dump(by_alias=True, mode="json"), "reasoning_content": "private"})
    return plan, run


def test_summary_projects_explicit_model_rationale_without_private_buffers():
    _, run = sources()
    before = json.dumps(run.execution_state)
    summary = initial_plan_summary(SimpleNamespace(), run)
    assert summary["tasks"][0]["rationale"] == "先核对事实，避免后续分析依赖假设"
    assert summary["constraints"] == ["不修改文件"]
    assert summary["objective"] == "分析故障"
    assert "private" not in json.dumps(summary)
    assert json.dumps(run.execution_state) == before


def test_initial_commit_is_available_before_graph_materialization_and_run_scoped():
    plan, run = sources()
    run.execution_state = {}
    record = SimpleNamespace(mission_id=run.mission_id, proposal_type="initial_plan", proposal_payload=plan,
        source_provenance=SimpleNamespace(source_run_id="run"), commit_id="accepted", commitment_revision=2)
    runtime = SimpleNamespace(planning_commit_authority=SimpleNamespace(store=SimpleNamespace(
        get_by_idempotency_key=lambda key: record if key == "initial-planning:run" else None)))
    summary = initial_plan_summary(runtime, run)
    assert summary["commitId"] == "accepted" and summary["commitmentRevision"] == 2
    record.source_provenance.source_run_id = "foreign"
    assert initial_plan_summary(runtime, run) is None


def review_run(**facts):
    return SimpleNamespace(status=WorkflowStatus.WAITING_REVIEW, updated_at=utc_now(), execution_state={
        "reviewPayload": {"subjectId": "graph", "subjectType": "planner", "observationId": "observation:1",
            "reasonCode": "PLANNER_WAIT",
            "reason": "Workspace review revision queued; settle the evidence barrier before formal graph activation"},
        **facts,
    })


def test_blocked_workspace_revision_uses_actual_rejection_and_never_offers_approval():
    reason = "Workspace review graph transition rejected: INVALID_PROPOSAL: started or settled work cannot be changed"
    run = review_run(workspaceReviewContinuation={"observationId": "observation:1", "blocked": True,
        "reason": reason, "errorType": "_TransitionRejected", "errorCode": "INVALID_PROPOSAL",
        "patch": {"private": "not a public display fact"}}, workspaceReview={"status": "blocked"})
    before = json.dumps(run.execution_state)
    result = review_summary(run)
    assert result["kind"] == "workspace_revision_blocked"
    assert result["reasonCode"] == "WORKSPACE_REVIEW_REVISION_BLOCKED"
    assert result["reason"] == reason
    assert "已开始或已有最终结果的步骤" in result["displayReason"]
    assert result["errorCode"] == "INVALID_PROPOSAL" and result["errorType"] == "_TransitionRejected"
    assert result["decisionRejected"] and not result["canApprove"]
    assert "private" not in json.dumps(result)
    assert json.dumps(run.execution_state) == before


def test_queued_workspace_revision_is_internal_work_and_not_an_external_confirmation():
    run = review_run(workspaceReviewContinuation={"observationId": "observation:1", "sourceGraphVersion": 1})
    result = review_summary(run)
    assert result["kind"] == "workspace_revision_pending"
    assert not result["canApprove"] and not result["decisionRejected"]
    assert "自动修订" in result["displayReason"]


def test_commit_rejection_is_current_diagnostic_even_when_the_round_was_applied_as_wait():
    run = review_run(planningCommitRejection={"observationId": "observation:1", "code": "INVALID_PROPOSAL",
        "reason": "started or settled work cannot be changed"})
    result = review_summary(run, SimpleNamespace(status="applied", rejection=None))
    assert result["kind"] == "planner_rejected" and result["reasonCode"] == "PLANNING_COMMIT_REJECTED"
    assert result["errorCode"] == "INVALID_PROPOSAL"
    assert result["decisionRejected"] and not result["canApprove"]


def test_stale_revision_diagnostics_do_not_replace_the_current_external_wait():
    run = review_run(workspaceReviewContinuation={"observationId": "older", "blocked": True},
        planningCommitRejection={"observationId": "older", "code": "INVALID_PROPOSAL", "reason": "old failure"})
    run.execution_state["reviewPayload"]["reason"] = "等待补充外部文件"
    result = review_summary(run)
    assert result["kind"] == "planner_wait" and result["reason"] == "等待补充外部文件"
    assert result["canApprove"] and not result["decisionRejected"]


def test_step_review_keeps_its_own_subject_and_is_not_a_workspace_revision_barrier():
    run = review_run(workspaceReviewContinuation={"observationId": "observation:1", "blocked": True})
    run.execution_state["reviewPayload"].update(subjectType="step", subjectId="read-1")
    result = review_summary(run)
    assert result["kind"] == "step_review" and result["subjectId"] == "read-1"
    assert result["canApprove"]


def test_unknown_execution_outcome_rejection_explains_the_missing_result():
    run = review_run(planningCommitRejection={"observationId": "observation:1",
        "code": "INVALID_PROPOSAL", "reason": "remote execution outcome is unknown"})
    result = review_summary(run)
    assert not result["canApprove"]
    assert "先核实执行结果" in result["displayReason"]


def test_planning_repair_progress_covers_wakeup_and_current_model_round_without_review():
    rejection = {"observationId": "denied-observation", "code": "INVALID_PROPOSAL", "reason": "PRIVATE"}
    run = SimpleNamespace(status=WorkflowStatus.RETRYING, execution_state={
        "planningCommitRejection": rejection, "planningLoop": {"restartPending": True},
    })
    before = json.dumps(run.execution_state)
    result = planning_progress(run)
    assert result["message"] == "正在根据审查反馈自动修正计划"
    assert result["kind"] == "repairing" and result["errorCode"] == "INVALID_PROPOSAL"
    assert "PRIVATE" not in json.dumps(result)
    assert json.dumps(run.execution_state) == before
    run.status = WorkflowStatus.RUNNING
    run.execution_state["planningLoop"] = {"restartPending": False, "current": {
        "status": "observed", "observation": {"planningCommitRejection": rejection},
    }}
    assert planning_progress(run)["kind"] == "repairing"
    run.execution_state["planningLoop"]["current"]["status"] = "applied"
    assert planning_progress(run) is None


def test_stale_feedback_and_review_barriers_are_not_active_planning_progress():
    rejection = {"observationId": "denied-observation", "code": "INVALID_PROPOSAL"}
    run = SimpleNamespace(status=WorkflowStatus.RUNNING, execution_state={
        "planningCommitRejection": rejection, "planningLoop": {"current": {
            "status": "observed", "observation": {"planningCommitRejection": {**rejection, "observationId": "different"}},
        }},
    })
    assert planning_progress(run) is None
    run.execution_state["planningLoop"] = {"restartPending": True}
    run.execution_state["reviewPayload"] = {"subjectType": "step"}
    assert planning_progress(run) is None
    run.execution_state.pop("reviewPayload")
    run.status = WorkflowStatus.WAITING_REVIEW
    assert planning_progress(run) is None
    run.status = WorkflowStatus.COMPLETED
    assert planning_progress(run) is None


def test_workspace_graph_handoff_is_visible_without_old_review_or_new_dispatch():
    run = SimpleNamespace(status=WorkflowStatus.RETRYING, execution_state={
        "graphVersion": 3, "reviewPayload": None,
        "planningLoop": {"current": {"observationId": "observation:2"}},
        "graphActivation": {"sourceGraphVersion": 2, "activeGraphVersion": 3, "executionPermit": None},
        "workspaceReviewContinuation": {"observationId": "observation:2", "sourceGraphVersion": 2,
            "patch": {"private": "not a public fact"}},
    })
    before = json.dumps(run.execution_state)
    result = planning_progress(run)
    assert result["kind"] == "repairing" and result["errorCode"] == "WORKSPACE_REVIEW_REVISION_PENDING"
    assert "交接" in result["message"] and result["observationId"] == "observation:2"
    assert "private" not in json.dumps(result) and json.dumps(run.execution_state) == before
    run.execution_state["graphActivation"]["executionPermit"] = {"permitId": "permit:3"}
    assert planning_progress(run) == result

    for change in ({"observationId": "older"}, {"sourceGraphVersion": 1}, {"blocked": True}):
        pending = run.execution_state["workspaceReviewContinuation"]
        run.execution_state["workspaceReviewContinuation"] = {**pending, **change}
        assert planning_progress(run) is None
        run.execution_state["workspaceReviewContinuation"] = pending
    run.status = WorkflowStatus.COMPLETED
    assert planning_progress(run) is None
    run.status = WorkflowStatus.RETRYING
    run.execution_state["reviewPayload"] = {"subjectType": "step"}
    assert planning_progress(run) is None


def test_copilot_view_publishes_the_blocked_revision_instead_of_the_queued_wait():
    from runtime.orchestration.planning_interaction import RuntimePlanningInteraction

    run = review_run(workspaceReviewContinuation={"observationId": "observation:1", "blocked": True,
        "reason": "Workspace review graph transition rejected: INVALID_PROPOSAL: started or settled work cannot be changed"})
    run.run_id, run.mission_id, run.runtime_revision, run.input, run.steps = "run", "mission", 5, {}, []
    store = SimpleNamespace(
        list_mission_run_summaries=lambda *_, **__: {"mission": SimpleNamespace(latest_run=None)},
        get_task_copilot_permission=lambda *_: "task_collaboration",
        list_task_copilot_exchanges=lambda *_: [],
    )
    runtime = SimpleNamespace(_intent_llm=None, workflow_store=store)
    before = json.dumps(run.execution_state)
    view = RuntimePlanningInteraction(runtime).view(run.run_id, run=run)
    assert view["question"] is None
    assert view["review"]["kind"] == "workspace_revision_blocked"
    assert not view["review"]["canApprove"]
    assert "started or settled" in view["review"]["reason"]
    assert "已开始或已有最终结果" in view["review"]["displayReason"]
    assert json.dumps(run.execution_state) == before

    run.status = WorkflowStatus.RETRYING
    run.execution_state = {"reviewPayload": None, "planningLoop": {"restartPending": True},
        "planningCommitRejection": {"observationId": "denied-observation", "code": "INVALID_PROPOSAL"}}
    active = RuntimePlanningInteraction(runtime).view(run.run_id, run=run)
    assert active["review"] is None and active["question"] is None
    assert active["planningProgress"]["message"] == "正在根据审查反馈自动修正计划"


def test_copilot_view_exposes_scope_effective_policy_and_resource_fallback():
    from contracts.task_operator_policy import TaskOperatorPolicy
    from runtime.orchestration.planning_interaction import RuntimePlanningInteraction

    run = review_run()
    run.run_id, run.mission_id, run.runtime_revision, run.steps = "run", "mission", 5, []
    run.input = {"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}}
    policy = TaskOperatorPolicy(missionId="mission", approvalMode="full", policyRevision=3,
        workspaceScope={**run.input["workspaceBinding"], "resourceId": "runtime"})
    store = SimpleNamespace(
        list_mission_run_summaries=lambda *_, **__: {"mission": SimpleNamespace(latest_run=None)},
        get_task_operator_policy=lambda *_: policy,
        list_task_copilot_exchanges=lambda *_: [],
    )
    runtime = SimpleNamespace(_intent_llm=None, workflow_store=store,
        local_runtime_resource=SimpleNamespace(profile=SimpleNamespace(runtime_id="runtime")))
    service = RuntimePlanningInteraction(runtime)
    view = service.view("run", run=run)
    assert view["approvalMode"] == "full" and view["policyRevision"] == 3
    assert view["approvalPolicy"]["effectiveScopeMatch"]
    assert "resourceId" not in run.input["workspaceBinding"]
    run.input["workspaceBinding"]["resourceId"] = "other"
    changed = service.view("run", run=run)
    assert changed["approvalMode"] == "ask"
    assert changed["approvalPolicy"]["approvalMode"] == "full"


def test_full_permission_request_requires_user_operation_and_independent_cas():
    import pytest
    from runtime.orchestration.planning_interaction import CopilotPermissionRequest

    request = CopilotPermissionRequest(permission="task_collaboration", approvalMode="full",
        operationId="selection", expectedPolicyRevision=0)
    assert request.approval_mode == "full" and request.expected_policy_revision == 0
    assert CopilotPermissionRequest(permission="read_only").approval_mode == "ask"
    for body in ({"permission": "read_only", "approvalMode": "full", "operationId": "selection", "expectedPolicyRevision": 0},
            {"permission": "task_collaboration", "approvalMode": "full"}):
        with pytest.raises(ValueError):
            CopilotPermissionRequest.model_validate(body)


def test_tool_timeline_reads_existing_receipts_without_model_or_file_contents(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    try:
        store.put_tool_value(run_id="run", step_id="step", key="result", payload={
            "record": {"executionId": "exec", "tool": "fs.read", "stepId": "step", "status": "completed"},
            "data": {"text": "private file body"}})
        store.put_tool_value(run_id="other", step_id="step", key="result", payload={
            "record": {"executionId": "foreign", "tool": "fs.read"}})
        store.put_tool_value(run_id="run", step_id="step", key="model", payload={"response": {"reasoning_content": "private"}})
        activity = store.list_tool_activity(run_id="run")
        assert len(activity) == 1 and activity[0]["executionId"] == "exec"
        assert "private" not in json.dumps(activity) and "foreign" not in json.dumps(activity)
    finally:
        store.close()


def test_copilot_progress_keeps_attempt_boundaries_and_first_response_timings(monkeypatch):
    from runtime.orchestration import planning_interaction as module
    current = [10.0]
    monkeypatch.setattr(module, 'monotonic', lambda: current[0])
    events = []
    progress = module._CopilotProgress(events.append, 10.0)
    progress.accept({'eventType': 'planner.stage.started'})
    current[0] = 10.2
    progress.accept({'eventType': 'planner.model.started', 'requestId': 'req-one'})
    current[0] = 11.0
    progress.accept({'eventType': 'planner.model.activity', 'reasoning_content': 'PRIVATE'})
    assert events[-1]['phase'] == 'receiving'
    assert events[-1]['requestId'] == 'req-one'
    assert all('PRIVATE' not in str(event) for event in events)
    progress.accept({'eventType': 'planner.model.output.delta', 'delta': '{"content":"first'})
    first_attempt = events[-1]['attemptId']
    progress.accept({'eventType': 'planner.stage.retry'})
    assert events[-1]['phase'] == 'retrying'
    progress.accept({'eventType': 'planner.stage.started'})
    assert events[-2]['content'] == '' and events[-2]['attemptId'] != first_attempt
    current[0] = 12.0
    progress.accept({'eventType': 'planner.model.started', 'requestId': 'req-two'})
    progress.accept({'eventType': 'planner.model.output.delta', 'delta': '{"content":"second","action":{"secret":"PRIVATE"}}'})
    assert events[-1]['content'] == 'second'
    assert 'PRIVATE' not in str(events)
    assert progress.metadata()['providerRequest'] == 2
    assert progress.metadata()['responseTimings'] == {'contextPreparationMs': 200, 'firstContentMs': 1000}
