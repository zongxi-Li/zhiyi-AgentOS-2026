"""Real independent worker projects Planner history without changing authority."""
from __future__ import annotations

from copy import deepcopy
import json
from time import monotonic
from types import SimpleNamespace

import pytest

from adapters import planning_context_projection as module
from adapters.model_adapter import StructuredGenerationError
from contracts.capability import ModelCapabilityEnvelope


class Model:
    def __init__(self, *, window=60_000, reserve=2_000, fail=False):
        self.capability = ModelCapabilityEnvelope(provider="offline", model="mock",
            contextWindowTokens=window, maxOutputTokens=reserve)
        self.calls = []
        self.fail = fail

    def describe_model(self):
        return self.capability

    def generate_json(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        if self.fail:
            raise ValueError("summary fixture failed")
        fields = schema["required"]
        return {"data": {key: ["Confirmed src/main.ts evidence; acceptance unchanged"] if key == "facts" else []
                         for key in fields}, "usage": {"total_tokens": 100}}


def observation():
    return SimpleNamespace(run_id="run-history", fingerprint=lambda: "observation-fingerprint")


def history(count=8, size=12_000):
    return [{"request": {"contextRef": "context:run-history:read:" + str(index), "fields": ["finding"]},
             "result": {"finding": "source src/main.ts " + str(index) + "x" * size},
             "meaning": "Previously stored evidence, no new task performed"} for index in range(count)]


SCHEMA = {"type": "object", "required": ["decision"], "properties": {"decision": {"type": "string"}}}
BASE = {"objective": "Review repository", "constraints": ["Read all source evidence"],
        "taskAcceptance": {"deliverable": "traceable report"},
        "contextCatalog": [{"contextRef": "context:source", "fields": ["finding"]}]}


def project(model, *, feedbacks=None, base=None, **kwargs):
    return module.project_planning_history(model, observation=observation(), base_request=base or BASE,
        feedbacks=history() if feedbacks is None else feedbacks, schema=SCHEMA,
        audit=kwargs.pop("audit", {}), deadline=monotonic() + 20, **kwargs)


@pytest.mark.parametrize("capability", ["short", "unknown_window", "unknown_output", "no_describer", "dict_capability"])
def test_short_or_unknown_budget_preserves_legacy_feedback_without_worker(monkeypatch, capability):
    model = Model(window=None if capability == "unknown_window" else 60_000,
                  reserve=None if capability == "unknown_output" else 2_000)
    if capability == "no_describer":
        model = object()
    if capability == "dict_capability":
        model.describe_model = lambda: model.capability.model_dump(by_alias=True, mode="json")
    monkeypatch.setattr(module, "_project_worker", lambda *a, **k: pytest.fail("short input must not spawn worker"))
    feedbacks = history(1, 20)
    base = {**BASE, "toolFeedback": []}
    result = project(model, feedbacks=feedbacks, base=base)
    assert result == {**base, "toolFeedback": feedbacks}


def test_real_worker_compacts_old_completed_feedback_and_preserves_authority_and_latest_tail():
    model, feedbacks, audit, snapshots = Model(), history(), {}, []
    original = deepcopy(feedbacks)
    result = project(model, feedbacks=feedbacks, audit=audit, snapshot_sink=lambda value: snapshots.append(value))

    assert {key: value for key, value in result.items() if key != "planningReadHistory"} == BASE
    assert "resultReadFeedback" not in result
    projected = result["planningReadHistory"]
    assert any("Historical conversation checkpoint" in item["content"] for item in projected)
    assert projected[-2]["role"] == "user" and projected[-1]["role"] == "assistant"
    assert json.loads(projected[-1]["content"])["planningReadFeedback"] == feedbacks[-1]
    assert feedbacks == original
    assert len(json.dumps(result)) < len(json.dumps({**BASE, "resultReadFeedback": feedbacks}))
    assert snapshots and snapshots[0]["sourceHash"] == audit["planningHistory"]["sourceHash"]
    assert audit["planningHistory"]["status"] == "summarized"
    assert "finding" not in json.dumps(audit)
    assert model.calls
    for call in model.calls:
        assert set(call["schema"]["required"]) == {
            "goals", "facts", "constraints", "completed", "decisions", "unresolved", "references", "tool_results"}
        assert call["schema"]["additionalProperties"] is False
        assert "Do not use tools" in call["system_prompt"]
        assert "tools" not in call and "tool_choice" not in call
        assert call["max_tokens"] <= model.capability.max_output_tokens


def test_persisted_projection_reuses_the_first_view_without_another_model_call():
    model, saved = Model(), {}
    first = project(model, snapshot_sink=lambda snapshot: saved.update(snapshot))
    calls = len(model.calls)
    second = project(model, snapshot_lookup=lambda source_hash: saved if source_hash == saved["sourceHash"] else None)
    assert first == second and len(model.calls) == calls
    assert saved["projectionHash"] == module._hash(saved["history"])


def test_same_history_reuses_snapshot_across_clocks_and_sessions_without_changing_current_authority():
    model, saved = Model(), {}
    first_base = {**BASE, "currentTime": "first-clock", "toolFeedback": [],
        "actionSession": {"sessionId": "first-session", "actionsUsed": 8, "allowedReads": ["context"]}}
    project(model, base=first_base, snapshot_sink=lambda snapshot: saved.update(snapshot))
    calls = len(model.calls)
    current = {**BASE, "currentTime": "later-clock", "toolFeedback": [],
        "actionSession": {"sessionId": "new-session", "actionsUsed": 0, "allowedReads": ["context"]}}
    result = project(model, base=current,
        snapshot_lookup=lambda source_hash: saved if source_hash == saved["sourceHash"] else None)
    assert len(model.calls) == calls
    assert result["currentTime"] == "later-clock" and result["actionSession"] == current["actionSession"]
    assert result["planningReadHistory"] == saved["history"]


def test_wrong_source_or_corrupt_projection_cannot_replace_current_history(monkeypatch):
    monkeypatch.setattr(module, "_project_worker", lambda *a, **k: pytest.fail("invalid cache must fail before worker"))
    with pytest.raises(StructuredGenerationError) as failure:
        project(Model(), snapshot_lookup=lambda _: {"version": module.VERSION, "sourceHash": "another-input", "history": []})
    assert failure.value.code == "PLANNING_CONTEXT_SNAPSHOT_INVALID"


def test_expired_deadline_does_not_launch_a_worker(monkeypatch):
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("deadline expired before worker admission"))
    with pytest.raises(StructuredGenerationError) as failure:
        module.project_planning_history(Model(), observation=observation(), base_request=BASE,
            feedbacks=history(), schema=SCHEMA, audit={}, deadline=monotonic() - 1)
    assert failure.value.code == "MODEL_TIMEOUT"


def test_protected_fixed_task_cannot_be_silently_shortened_when_it_exceeds_model_capacity():
    model = Model(window=16_000)
    base = {**BASE, "constraints": ["explicit authoritative requirement " * 1_000]}
    with pytest.raises(StructuredGenerationError) as failure:
        project(model, feedbacks=history(3, 2_000), base=base)
    assert failure.value.code == "MODEL_INPUT_BUDGET_EXCEEDED"
    assert base["constraints"] == ["explicit authoritative requirement " * 1_000]


def test_failed_summary_retains_original_history_when_it_still_fits_real_window():
    model = Model(window=100_000, fail=True)
    feedbacks = history(7, 12_000)
    audit = {}
    result = project(model, feedbacks=feedbacks, audit=audit)
    assert result == {**BASE, "resultReadFeedback": feedbacks}
    assert audit["planningHistory"]["status"] == "failed_passthrough"
