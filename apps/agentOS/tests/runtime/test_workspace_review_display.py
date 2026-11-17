from copy import deepcopy
from types import SimpleNamespace

import pytest

from runtime.workspace_review_display import workspace_review_projection, with_workspace_review, workspace_transition_failure


@pytest.mark.parametrize("stale", [None, "activation", "observation", "graph", "resumed", "permit", "terminal"])
def test_transition_failure_only_displays_current_paused_boundary(stale):
    run = SimpleNamespace(status="retrying", execution_state={"graphVersion": 2,
        "graphActivation": {"activationId": "activation:2", "executionPermit": None},
        "workspaceReviewContinuation": {"observationId": "observation:1"}})
    payload = {"activationId": "activation:2", "observationId": "observation:1", "graphVersion": 2,
        "errorCode": "INVALID_PROPOSAL", "errorType": "_TransitionRejected",
        "authorityReason": "current origin differs from accepted frozen provenance", "private": "not-public"}
    event = {"eventType": "workspace.review.blocked", "payload": payload}
    if stale in {"activation", "observation", "graph"}:
        payload[{"activation": "activationId", "observation": "observationId", "graph": "graphVersion"}[stale]] = "older"
    elif stale == "permit":
        run.execution_state["graphActivation"]["executionPermit"] = {"permitId": "permit:2"}
    elif stale == "terminal":
        run.status = "completed"
    events = [event]
    if stale == "resumed":
        events.append({"eventType": "workspace.review.resumed", "payload": {"status": "resumed"}})
    before = deepcopy(run.execution_state)
    result = workspace_transition_failure(run, {"events": events})
    if stale is None:
        assert result["kind"] == result["status"] == "blocked"
        assert result["reason"] == payload["authorityReason"] and result["canApprove"] is False
        assert "private" not in result and "patch" not in result
    else:
        assert result is None
    assert run.execution_state == before


def test_copilot_view_reads_persisted_handoff_reason_without_turning_it_into_an_approval():
    from contracts.workflow import RuntimeRunRecord, WorkflowStatus
    from runtime.planning_interaction import RuntimePlanningInteraction

    run = RuntimeRunRecord(runId="run", missionId="mission", workflowId="flow", domain="general",
        runtimeEngine="acg", status=WorkflowStatus.RETRYING,
        executionState={"graphVersion": 2,
            "graphActivation": {"activationId": "activation:2", "executionPermit": None},
            "workspaceReviewContinuation": {"observationId": "observation:1"}})
    display = {"events": [{"eventType": "workspace.review.blocked", "payload": {
        "activationId": "activation:2", "observationId": "observation:1", "graphVersion": 2,
        "errorCode": "INVALID_PROPOSAL", "authorityReason": "current origin differs from accepted frozen provenance"}}]}
    store = SimpleNamespace(get_runtime_display=lambda _: display,
        list_mission_run_summaries=lambda *a, **kw: {"mission": SimpleNamespace(latest_run=run)},
        get_task_copilot_permission=lambda _: "task_collaboration", list_task_copilot_exchanges=lambda _: [])
    runtime = SimpleNamespace(workflow_store=store, get_status_cached=lambda _: run, _intent_llm=None)
    before = run.model_copy(deep=True)
    result = RuntimePlanningInteraction(runtime).view("run")
    assert result["planningProgress"]["kind"] == "blocked"
    assert result["planningProgress"]["reason"] == display["events"][0]["payload"]["authorityReason"]
    assert result["planningProgress"]["canApprove"] is False and result["review"] is None
    assert run == before


def review_fact():
    return {
        "schemaVersion": 1, "round": 2, "graphVersion": 3, "status": "reading",
        "gaps": {"missingReadCount": 105, "missingListingCount": 8, "unsupportedEntryCount": 1,
                 "missingReads": ["src/main.py"], "missingListings": ["tests"], "unsupportedEntries": ["link"]},
        "rounds": [{"round": 1, "graphVersion": 2, "action": "revise", "reason": "Read remaining evidence",
                    "stepIds": ["read-1", "review-1"], "addedStepIds": ["read-1", "review-1"],
                    "observationRef": "observation:1", "decisionRef": "decision:1", "patchRef": "patch:1",
                    "traceRefs": ["trace:1"]}],
    }


def test_review_projection_preserves_runtime_counts_rounds_and_references_without_mutation():
    fact = review_fact()
    fact["private"] = {"grantId": "do-not-publish"}
    fact["gaps"]["arguments"] = {"password": "do-not-publish"}
    fact["rounds"][0]["rawResponse"] = "do-not-publish"
    run = SimpleNamespace(execution_state={"workspaceReview": fact})
    before = deepcopy(run.execution_state)
    public = workspace_review_projection(run)
    assert public == review_fact()
    assert run.execution_state == before
    assert public["gaps"]["missingReadCount"] == 105  # Counts are not path-sample lengths.
    public["rounds"][0]["traceRefs"].append("display-only")
    assert run.execution_state == before


@pytest.mark.parametrize("invalid", [None, {}, {"schemaVersion": 2}, {**review_fact(), "round": -1},
                                        {**review_fact(), "status": "completed-without-proof"}])
def test_invalid_or_absent_review_facts_are_not_inferred(invalid):
    assert workspace_review_projection(SimpleNamespace(execution_state={"workspaceReview": invalid})) is None


@pytest.mark.parametrize("path", ["C:/private/file", "../secret", "/private", ""])
def test_review_projection_never_exposes_absolute_or_traversing_path_samples(path):
    fact = review_fact()
    fact["gaps"]["missingReads"] = [path]
    assert workspace_review_projection(SimpleNamespace(execution_state={"workspaceReview": fact})) is None


def test_join_requires_matching_formal_graph_and_does_not_add_nodes_or_edges():
    run = SimpleNamespace(execution_state={"workspaceReview": review_fact()})
    graph = {"graphId": "g", "graphVersion": 3, "nodes": [{"nodeId": "read-1"}], "edges": []}
    before = deepcopy(graph)
    result = with_workspace_review(graph, run)
    assert result == {**before, "workspaceReview": review_fact()}
    assert graph == before
    assert with_workspace_review({**graph, "graphVersion": 2}, run) == {**before, "graphVersion": 2}
    assert with_workspace_review(None, run) is None


def test_missing_review_does_not_change_legacy_projection():
    graph = {"graphVersion": 1, "nodes": [], "edges": []}
    assert with_workspace_review(graph, SimpleNamespace(execution_state={})) is graph


def test_copilot_reads_the_same_review_facts_and_keeps_existing_tool_activity():
    from contracts.workflow import WorkflowStatus
    from runtime.planning_interaction import RuntimePlanningInteraction

    run = SimpleNamespace(run_id="run", mission_id="mission", status=WorkflowStatus.RUNNING,
                          runtime_revision=4, input={}, steps=[], execution_state={"workspaceReview": review_fact()})
    store = SimpleNamespace(
        list_mission_run_summaries=lambda *_, **__: {"mission": SimpleNamespace(latest_run=None)},
        get_task_copilot_permission=lambda *_: "read_only",
        list_task_copilot_exchanges=lambda *_: [],
    )
    tools = [{"executionId": "tool:1", "tool": "fs.read", "status": "completed", "target": "src/main.py"}]
    runtime = SimpleNamespace(_intent_llm=None, workflow_store=store,
                              execution_value_store=SimpleNamespace(list_tool_activity=lambda **_: tools))
    public = RuntimePlanningInteraction(runtime).view("run", run=run)
    assert public["workspaceReview"] == review_fact()
    assert public["toolActivity"] == tools
