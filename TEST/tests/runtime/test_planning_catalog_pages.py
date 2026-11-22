"""Large planning directories are queried in complete reproducible pages."""
import pytest

from components.executor.value_store import SQLiteExecutionValueStore
from contracts import stable_checksum
from contracts.planning_results import PlanningResultRead, planning_observation_view, planning_result_operation_id
from contracts.runtime_planning import PlanningContextIndexEntry, PlanningResultField, RuntimePlanningObservation
from runtime.orchestration.planning_results import read_planning_result_page
from types import SimpleNamespace


@pytest.fixture
def directory(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    store = SQLiteExecutionValueStore(db_path=path)
    field = PlanningResultField(name="content", present=True, valueType="str", byteLength=20, estimatedTokens=6)
    entries = tuple(PlanningContextIndexEntry(contextRef=f"frozen-context:{index}",
        contextKind="tool_result" if index % 2 else "attempt_input", title=f"Saved context {index}",
        sourceRunId="run", stepId=f"step-{index % 5}", attemptId=f"attempt-{index}", status="candidate",
        trust="agent_generated", checksum=str(index), byteLength=20, estimatedTokens=6, fields=(field,))
        for index in range(1000))
    observation = RuntimePlanningObservation(missionId="mission", runId="run", graphId="graph",
        graphVersion=2, planVersion=2, wakeReason="resume", goal="Inspect saved contexts", steps=(),
        remainingStepIds=(), contextCatalog=entries)
    return SimpleNamespace(execution_value_store=store), observation, path


def test_all_thousand_directory_entries_are_reconstructible_without_injecting_them_into_prompt(directory):
    services, observation, _ = directory
    view = planning_observation_view(observation)
    assert view["contextCatalog"]["count"] == 1000
    assert sum(group["count"] for group in view["contextCatalog"]["groups"]) == 1000
    assert len(str(view)) < len(observation.model_dump_json()) / 20
    seen, cursor = [], None
    while True:
        page = read_planning_result_page(services, observation, catalog="contexts", cursor=cursor,
            page_tokens=5000, operation_id=f"catalog-{len(seen)}")
        seen.extend(page["data"]["entries"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert seen == [entry.model_dump(by_alias=True, mode="json") for entry in observation.context_catalog]


def test_catalog_filters_cursor_ownership_restart_and_structure_lookup(directory):
    services, observation, path = directory
    args = dict(catalog="contexts", context_kind="tool_result", step_id="step-1", page_tokens=5000,
        operation_id="filtered-first")
    first = read_planning_result_page(services, observation, **args)
    assert first["count"] == 100 and first["nextCursor"]
    assert all(entry["contextKind"] == "tool_result" and entry["stepId"] == "step-1"
        for entry in first["data"]["entries"])
    reopened = SimpleNamespace(execution_value_store=SQLiteExecutionValueStore(db_path=path))
    assert read_planning_result_page(reopened, observation, **args) == first
    for change in ({"context_kind": "attempt_input"}, {"step_id": "step-3"}):
        with pytest.raises(ValueError, match="cursor belongs"):
            read_planning_result_page(reopened, observation, **{**args, **change,
                "cursor": first["nextCursor"], "operation_id": "invalid-cursor"})
    changed = observation.model_copy(update={"graph_version": 3})
    with pytest.raises(ValueError, match="cursor belongs"):
        read_planning_result_page(reopened, changed, **{**args, "cursor": first["nextCursor"],
            "operation_id": "changed-version"})
    structure = read_planning_result_page(services, observation, catalog="contexts", context_kind="tool_result",
        step_id="step-1", path=[0], describe=True, operation_id="entry-shape")
    assert structure["data"]["description"]["valueType"] == "dict"
    assert any(child["key"] == "contextRef" for child in structure["data"]["description"]["children"])


def test_result_catalog_empty_filter_and_old_operation_identity_remain_compatible(directory):
    services, observation, _ = directory
    page = read_planning_result_page(services, observation, catalog="results", operation_id="empty-results")
    assert page["count"] == 0 and page["data"] == {"entries": []} and page["nextCursor"] is None
    legacy_arguments = {"step_id": "A", "output_ref": None, "context_ref": None, "fields": ("answer",),
        "cursor": None, "page_tokens": 2048, "path": (), "describe": False}
    new_arguments = {**legacy_arguments, "catalog": None, "context_kind": None}
    assert planning_result_operation_id(observation, new_arguments) == "planner-result:" + stable_checksum(
        [observation.fingerprint(), legacy_arguments])
    assert PlanningResultRead(catalog="contexts", contextKind="tool_result", stepId="A").context_kind == "tool_result"
    for bad in ({"catalog": "contexts", "contextRef": "x"}, {"catalog": "results", "contextKind": "tool"},
                {"contextKind": "tool", "stepId": "A"}):
        with pytest.raises(ValueError):
            PlanningResultRead.model_validate(bad)


@pytest.mark.parametrize("query", [
    {"fields": ["invented"]}, {"page_tokens": 0}, {"page_tokens": True},
    {"page_tokens": 1}, {"cursor": "another-observation:0:0"},
    {"path": [1000]}, {"path": [0, "missing"]},
    {"cursor": "invalid", "describe": True},
])
def test_invalid_catalog_queries_do_not_create_durable_values(directory, query):
    services, observation, _ = directory
    store = services.execution_value_store
    before = store.list_tool_references(run_id=observation.run_id)
    with pytest.raises((ValueError, PermissionError)):
        read_planning_result_page(services, observation, **{
            "catalog": "contexts", "page_tokens": 5000, "operation_id": "invalid-query", **query})
    assert store.list_tool_references(run_id=observation.run_id) == before


def test_invalid_bound_cursor_and_operation_conflict_create_no_extra_values(directory):
    services, observation, _ = directory
    store = services.execution_value_store
    first = read_planning_result_page(services, observation, catalog="contexts",
        page_tokens=5000, operation_id="first-page")
    before = store.list_tool_references(run_id=observation.run_id)
    owner = first["nextCursor"].split(":", 1)[0]
    with pytest.raises((ValueError, PermissionError)):
        read_planning_result_page(services, observation, catalog="contexts", cursor=owner + ":bad-offset",
            page_tokens=5000, operation_id="invalid-offset")
    with pytest.raises(ValueError, match="operation_id conflicts"):
        read_planning_result_page(services, observation, catalog="contexts", context_kind="tool_result",
            page_tokens=5000, operation_id="first-page")
    assert store.list_tool_references(run_id=observation.run_id) == before
