"""Runtime callback ownership survives process/store reconstruction."""
from __future__ import annotations

from copy import deepcopy
import sqlite3
from time import monotonic

import pytest

from adapters.model import planning_context_projection as projection
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.capability import ModelCapabilityEnvelope
from contracts.runtime_planning import RuntimePlanningObservation
from runtime.workflow_runtime import ExecutionRuntime


class RuntimeProjectionHost:
    """Only the production callback's existing execution-store dependency."""
    _project_planning_context = ExecutionRuntime._project_planning_context

    def __init__(self, values):
        self.execution_value_store = values


class SummaryModel:
    def __init__(self, *, forbid_calls=False):
        self.calls = 0
        self.forbid_calls = forbid_calls

    def describe_model(self):
        return ModelCapabilityEnvelope(provider="offline", model="mock",
                                       contextWindowTokens=60_000, maxOutputTokens=2_000)

    def generate_json(self, prompt, schema, **kwargs):
        assert not self.forbid_calls, "persisted source history must not be summarized again"
        self.calls += 1
        return {"data": {key: ["confirmed source result"] if key == "facts" else [] for key in schema["required"]}}


def observation(run_id="run_history"):
    return RuntimePlanningObservation(missionId="mission_0123456789ab", runId=run_id,
        graphId="graph", graphVersion=1, planVersion=1, wakeReason="failure", goal="Review source",
        steps=(), remainingStepIds=())


def inputs(session="first", clock="first-clock"):
    return {"objective": "Review all accepted source evidence",
            "constraints": ["Keep the original acceptance and receipt references"],
            "taskAcceptance": {"deliverable": "verified report"}, "currentTime": clock,
            "actionSession": {"sessionId": session, "actionsUsed": 0, "allowedReads": ["step_output"]},
            "toolFeedback": []}


def feedbacks():
    return [{"request": {"contextRef": "context:source:" + str(index), "cursor": None},
             "result": {"data": "confirmed src/main.py " + "x" * 12_000}}
            for index in range(8)]


SCHEMA = {"type": "object", "required": ["decision"], "properties": {"decision": {"type": "string"}}}


def invoke(host, model, obs, *, base=None, history=None, audit=None):
    return host._project_planning_context(model, observation=obs, base_request=base or inputs(),
        feedbacks=history if history is not None else feedbacks(), schema=SCHEMA,
        audit=audit if audit is not None else {}, deadline=monotonic() + 20)


def snapshots(store, run_id):
    return [store.get_output(run_id=run_id, output_ref=ref.reference)
            for ref in store.list_tool_references(run_id=run_id)]


def test_runtime_reuses_persisted_projection_after_restart_and_new_planning_session(tmp_path):
    database = tmp_path / "values.sqlite3"
    store = SQLiteExecutionValueStore(db_path=database)
    model, obs, audit = SummaryModel(), observation(), {}
    try:
        first = invoke(RuntimeProjectionHost(store), model, obs, audit=audit)
        assert model.calls > 0
        source_hash = audit["planningHistory"]["sourceHash"]
        key = "planning-history:" + obs.fingerprint() + ":" + source_hash
        saved = store.get_tool_value(run_id=obs.run_id, key=key)
        assert saved["history"] == first["planningReadHistory"]
        assert saved["sourceHash"] == source_hash
        assert len(snapshots(store, obs.run_id)) == 1
    finally:
        store.close()

    reopened = SQLiteExecutionValueStore(db_path=database)
    try:
        new_model = SummaryModel(forbid_calls=True)
        current = inputs("new-session-after-restart", "later-clock")
        current["actionSession"]["actionsUsed"] = 22
        replay_audit = {}
        resumed = invoke(RuntimeProjectionHost(reopened), new_model, obs, base=current, audit=replay_audit)
        assert new_model.calls == 0
        assert resumed["planningReadHistory"] == first["planningReadHistory"]
        assert resumed["currentTime"] == current["currentTime"]
        assert resumed["actionSession"] == current["actionSession"]
        assert replay_audit["planningHistory"]["sourceHash"] == source_hash
        assert reopened.get_tool_value(run_id=obs.run_id, key=key) == saved
        assert len(snapshots(reopened, obs.run_id)) == 1
    finally:
        reopened.close()


def test_changed_reader_cursor_gets_a_new_source_projection_and_other_runs_do_not_reuse_it(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    host, model, obs = RuntimeProjectionHost(store), SummaryModel(), observation()
    try:
        first_audit, next_audit = {}, {}
        invoke(host, model, obs, audit=first_audit)
        changed = feedbacks()
        changed[-1]["request"]["cursor"] = "next-source-page"
        invoke(host, model, obs, history=changed, audit=next_audit)
        assert next_audit["planningHistory"]["sourceHash"] != first_audit["planningHistory"]["sourceHash"]
        assert len(snapshots(store, obs.run_id)) == 2
        other = observation("run_other")
        before = model.calls
        invoke(host, model, other)
        assert model.calls > before
        assert len(snapshots(store, other.run_id)) == 1
        assert len(snapshots(store, obs.run_id)) == 2
    finally:
        store.close()


@pytest.mark.parametrize("conflict_type", [ValueError, sqlite3.IntegrityError])
def test_runtime_save_keeps_first_snapshot_when_another_session_wins_admission(tmp_path, monkeypatch, conflict_type):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    obs = observation()
    candidate = {"sourceHash": "source", "history": [{"role": "user", "content": "candidate view"}]}
    winner = {**candidate, "history": [{"role": "user", "content": "first committed view"}]}
    put = store.put_tool_value

    def competing_write(**kwargs):
        put(**{**kwargs, "payload": deepcopy(winner)})
        raise conflict_type("another planner session sealed this source first")

    def inspect_projection(llm, *, snapshot_lookup, snapshot_sink, **kwargs):
        assert snapshot_lookup("source") is None
        return snapshot_sink(candidate)

    monkeypatch.setattr(store, "put_tool_value", competing_write)
    monkeypatch.setattr(projection, "project_planning_history", inspect_projection)
    try:
        result = invoke(RuntimeProjectionHost(store), object(), obs)
        assert result == winner
        assert snapshots(store, obs.run_id) == [winner]
    finally:
        store.close()


def test_runtime_does_not_hide_a_storage_failure_without_a_sealed_snapshot(tmp_path, monkeypatch):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    failure = ValueError("storage failed before sealing")

    def failing_write(**kwargs):
        raise failure

    def inspect_projection(llm, *, snapshot_sink, **kwargs):
        return snapshot_sink({"sourceHash": "source", "history": []})

    monkeypatch.setattr(store, "put_tool_value", failing_write)
    monkeypatch.setattr(projection, "project_planning_history", inspect_projection)
    try:
        with pytest.raises(ValueError) as captured:
            invoke(RuntimeProjectionHost(store), object(), observation())
        assert captured.value is failure
    finally:
        store.close()
