import json
from types import SimpleNamespace

from components.executor.value_store import SQLiteExecutionValueStore
from contracts.planning import TaskPlan, PlannedTask
from runtime.copilot_projection import initial_plan_summary


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
