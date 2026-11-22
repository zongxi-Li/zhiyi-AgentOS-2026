"""Planner diagnostics can inspect all saved Run contexts without promoting them."""
import asyncio
from datetime import timedelta
import sqlite3
import json
from types import SimpleNamespace

import pytest

from components.executor.graph import ACGSuperstepError
from components.executor.value_store import SQLiteExecutionValueStore
from contracts import stable_checksum
from contracts.memory import MemoryRecord
from contracts.planning_context import PLANNING_CONTEXT_OWNER, planning_context_key, planning_context_reference
from contracts.runtime_planning import (
    RuntimePlanningDecision, RuntimePlanningObservation, RuntimePlanningRound, RuntimePlanningState,
)
from contracts.workflow import utc_now
from runtime.orchestration.planning_context_catalog import build_planning_context_catalog
from runtime.orchestration.planning_results import read_planning_result_page
from runtime.orchestration.state_persistence import acg_execution_state_from_run
from runtime.orchestration.workspace_planning_context import workspace_discovery_snapshot
from TEST.tests.runtime.test_planning_loop import Agent, Planner, attach, prepared, runtime_at
from TEST.tests.contracts.test_execution_evidence import EvidenceRun


def with_catalog(runtime, run, observation):
    return observation.model_copy(update={"context_catalog": build_planning_context_catalog(runtime, run)})


def read_entry(runtime, observation, kind, *, fields=(), **kwargs):
    entry = next(entry for entry in observation.context_catalog if entry.context_kind == kind)
    return read_planning_result_page(runtime, observation, context_ref=entry.context_ref,
        fields=fields, operation_id=f"read-{kind}-{stable_checksum(kwargs)}", **kwargs)


def test_failed_attempt_input_and_frozen_memory_are_readable_without_committed_output(tmp_path):
    runtime, _, run = prepared(tmp_path, Agent(fail=True), input={"goal": "legacy task objective",
        "constraints": ["keep the useful prefix"], "materialText": "supplied material", "apiKey": "HOST SECRET"})
    attach(runtime, Planner(lambda observation, _: RuntimePlanningDecision(observationId=observation.fingerprint(),
        action="abort", reason="record failed execution")))
    with pytest.raises(ACGSuperstepError):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    failed = runtime.workflow_store.get_run(run.run_id)
    observation = runtime.runtime_planning_coordinator.observe(failed, acg_execution_state_from_run(failed), "failure")
    inputs = [entry for entry in observation.context_catalog if entry.context_kind == "attempt_input" and entry.step_id == "B"]
    assert len(inputs) == 1 and inputs[0].status == "prepared"
    assert "B" not in failed.execution_state["outputRefs"]
    page = read_planning_result_page(runtime, observation, context_ref=inputs[0].context_ref,
        fields=["sourceData"], describe=True, operation_id="failed-input-shape")
    assert page["data"]["description"]["valueType"] == "dict"
    memory = [entry for entry in observation.context_catalog if entry.context_kind == "memory_retrieval"]
    assert memory and all(entry.status != "unavailable" for entry in memory)
    assert read_entry(runtime, observation, "task_request", fields=["request"])["data"]["request"]["goal"] == "legacy task objective"
    assert read_entry(runtime, observation, "task_materials", fields=["materialText"])["data"] == {"materialText": "supplied material"}
    assert "HOST SECRET" not in str([read_planning_result_page(runtime, observation, context_ref=entry.context_ref,
        fields=[field.name], operation_id=f"check-{entry.context_ref}-{field.name}")
        for entry in observation.context_catalog if entry.context_kind in {"task_request", "task_materials"}
        for field in entry.fields])


def test_tool_retrieval_and_model_contexts_keep_business_content_but_drop_transport_credentials(tmp_path):
    runtime, _, run = prepared(tmp_path)
    attach(runtime, Planner())
    final = asyncio.run(runtime.execute_prepared_run(run.run_id))
    store = runtime.execution_value_store
    identity = {"runId": run.run_id, "stepId": "B", "attemptId": "attempt", "commitId": "operation"}
    store.put_tool_value(run_id=run.run_id, step_id="B", key="request", payload={"identity": identity,
        "request": {"capabilityId": "plugin.lookup", "resourceId": "plugin", "headers": {"Authorization": "PRIVATE"},
            "authorization": {"workspaceId": "workspace", "grantId": "grant", "secret": "PRIVATE"},
            "environment": {"TOKEN": "PRIVATE"},
            "input": {"query": "repository invariants", "filters": {"module": "planner"}, "token": "business identifier"}}})
    result = {"text": "retrieved business source", "model": "fixture", "metadata": {"apiKey": "PRIVATE"},
        "sources": [{"title": "Reference", "url": "https://example.test", "content": "evidence body", "headers": "PRIVATE"}]}
    store.put_tool_value(run_id=run.run_id, step_id="B", key="retrieval", payload={"identity": identity,
        "retrievalRequestHash": "request-hash", "resultHash": stable_checksum(result), "result": result})
    store.put_tool_value(run_id=run.run_id, step_id="B", key="generic", payload={"name": "plugin.lookup",
        "source": "plugin", "status": "succeeded", "output": {"customBusinessField": "useful value"}})
    store.put_tool_value(run_id=run.run_id, step_id="B", key="recorded-business", payload={
        "record": {**identity, "tool": "plugin.lookup", "status": "completed", "metadata": {"secret": "PRIVATE"}},
        "data": {"customBusinessField": {"nested": ["complete result", {"token": "business value"}]}}})
    store.put_tool_value(run_id=run.run_id, step_id="B", key="receipt-business", payload={
        "identity": identity, "status": "completed", "headers": {"Authorization": "PRIVATE"},
        "output": {"customBusinessField": {"nested": ["receipt result", {"customMetric": 42}]}}})
    store.put_tool_value(run_id=run.run_id, step_id="B", key="model", payload={"requestHash": "model-hash",
        "response": {"requestId": "model-request", "content": {"answer": "candidate answer"},
            "metadata": {"token": "PRIVATE"}, "assistantMessage": {"content": "public answer", "reasoning_content": "PRIVATE"},
            "toolCalls": [{"function": {"name": "plugin__lookup",
                "arguments": '{"query":"repository invariants","filters":{"module":"planner"},"token":"business identifier"}'}}]}})
    observation = runtime.runtime_planning_coordinator.observe(final, acg_execution_state_from_run(final), "resume")
    requested = read_entry(runtime, observation, "tool_request", fields=["request"])
    assert requested["data"]["request"]["input"] == {"query": "repository invariants",
        "filters": {"module": "planner"}, "token": "business identifier"}
    retrieved = read_entry(runtime, observation, "retrieval_result", fields=["result"])
    assert retrieved["data"]["result"]["text"] == "retrieved business source"
    generic = read_entry(runtime, observation, "agent_tool_result", fields=["output"])
    assert generic["data"] == {"output": {"customBusinessField": "useful value"}}
    recorded = read_entry(runtime, observation, "tool_result", fields=["output"])
    assert recorded["data"]["output"] == {"customBusinessField": {
        "nested": ["complete result", {"token": "business value"}]}}
    receipt = read_entry(runtime, observation, "tool_receipt", fields=["output"])
    assert receipt["data"]["output"] == {"customBusinessField": {
        "nested": ["receipt result", {"customMetric": 42}]}}
    model = read_entry(runtime, observation, "model_turn", fields=["response"])
    assert model["data"]["response"]["content"] == {"answer": "candidate answer"}
    assert json.loads(model["data"]["response"]["toolCalls"][0]["arguments"])["query"] == "repository invariants"
    assert "PRIVATE" not in str((requested, retrieved, generic, recorded, receipt, model))


def test_context_snapshot_and_nested_pages_survive_restart_and_ignore_later_or_other_run_memory(tmp_path):
    runtime, _, run = prepared(tmp_path, input={"sourceMaterials": {"section": {"large": "saved context " * 250}}})
    attach(runtime, Planner())
    final = asyncio.run(runtime.execute_prepared_run(run.run_id))
    runtime.memory_store.put(MemoryRecord(memoryId="mine", memoryType="episodic", scope=run.run_id,
        content={"answer": "original memory"}))
    runtime.memory_store.put(MemoryRecord(memoryId="other", memoryType="episodic", scope="another-run",
        content={"answer": "FOREIGN"}))
    runtime.memory_store.put(MemoryRecord(memoryId="expired", memoryType="episodic", scope=run.run_id,
        expiresAt=utc_now() - timedelta(days=1), content={"answer": "EXPIRED"}))
    patch_ref = runtime.execution_value_store.put_graph_patch(run_id=run.run_id,
        payload={"reason": "retained source for planning diagnostics"})
    observation = runtime.runtime_planning_coordinator.observe(final, acg_execution_state_from_run(final), "resume")
    entry = next(entry for entry in observation.context_catalog if entry.context_kind == "task_materials")
    first = read_planning_result_page(runtime, observation, context_ref=entry.context_ref, fields=["sourceMaterials"],
        path=["section", "large"], page_tokens=70, operation_id="nested-first")
    assert first["path"] == ["section", "large"] and first["nextCursor"]
    loop = RuntimePlanningState.model_validate(final.execution_state["planningLoop"])
    final.execution_state["planningLoop"] = loop.model_copy(update={"current": RuntimePlanningRound(
        observationId=observation.fingerprint(), observation=observation)}).model_dump(by_alias=True, mode="json")
    runtime.workflow_store.save_run(final)
    orphan = runtime.execution_value_store.put_context_pack(run_id=run.run_id, step_id="orphan",
        payload={"unowned": "remove this context"})
    stats = runtime.clean_execution_orphans(run_id=run.run_id, older_than=utc_now() + timedelta(seconds=1))
    assert stats.deleted == 1
    with pytest.raises(ValueError):
        runtime.execution_value_store.get_context_pack(run_id=run.run_id, context_ref=orphan)
    assert runtime.execution_value_store.get_graph_patch(run_id=run.run_id,
        patch_ref=patch_ref)["reason"] == "retained source for planning diagnostics"
    reopened, _ = runtime_at(tmp_path)
    assert read_planning_result_page(reopened, observation, context_ref=entry.context_ref, fields=["sourceMaterials"],
        path=["section", "large"], page_tokens=70, operation_id="nested-first") == first
    memories = [read_planning_result_page(runtime, observation, context_ref=item.context_ref,
        fields=["memory"], operation_id=f"memory-{index}")["data"]["memory"]
        for index, item in enumerate(observation.context_catalog) if item.context_kind == "run_memory"]
    assert any(item["memoryId"] == "mine" for item in memories)
    assert all(item["memoryId"] != "other" for item in memories)
    assert any(item["memoryId"] == "expired" for item in memories)
    assert next(item for item in observation.context_catalog if "expired" in item.title).status == "expired"
    runtime.memory_store.put(MemoryRecord(memoryId="mine", memoryType="episodic", scope=run.run_id,
        content={"answer": "changed later"}))
    old = next(item for item in observation.context_catalog if item.context_kind == "run_memory"
        and "mine" in item.title)
    assert read_planning_result_page(runtime, observation, context_ref=old.context_ref, fields=["memory"],
        operation_id="old-memory")["data"]["memory"]["content"] == {"answer": "original memory"}
    with pytest.raises(ValueError, match="cannot be combined"):
        read_planning_result_page(runtime, observation, context_ref=entry.context_ref, step_id="A", operation_id="mixed")


def test_reobserving_same_frontier_does_not_change_catalog_identity_or_repeat_its_own_snapshots(tmp_path):
    runtime, _, run = prepared(tmp_path)
    attach(runtime, Planner())
    final = asyncio.run(runtime.execute_prepared_run(run.run_id))
    first = runtime.runtime_planning_coordinator.observe(final, acg_execution_state_from_run(final), "resume")
    second = runtime.runtime_planning_coordinator.observe(final, acg_execution_state_from_run(final), "resume")
    assert first.context_catalog == second.context_catalog
    assert first.fingerprint() == second.fingerprint()
    assert all(item.context_kind != "planning_context" for item in first.context_catalog)


def test_single_corrupt_context_is_cataloged_as_unavailable_without_hiding_storage_failure(tmp_path, monkeypatch):
    runtime, _, run = prepared(tmp_path)
    attach(runtime, Planner())
    final = asyncio.run(runtime.execute_prepared_run(run.run_id))
    store = runtime.execution_value_store
    original = store.get_node_input_context
    executions = store.list_node_executions(run_id=run.run_id)
    corrupt_operation = executions[0].operation_id

    def damaged_input(*, run_id, operation_id):
        if operation_id == corrupt_operation:
            return {"runId": run_id, "stepId": None}
        return original(run_id=run_id, operation_id=operation_id)

    monkeypatch.setattr(store, "get_node_input_context", damaged_input)
    bad_tool = store.put_tool_value(run_id=run.run_id, step_id="B", key="malformed-result",
        payload={"name": "plugin.lookup", "source": "plugin", "status": "succeeded", "output": ["wrong shape"]})
    entries = build_planning_context_catalog(runtime, final)
    invalid_input = next(entry for entry in entries if entry.operation_id == corrupt_operation and entry.context_kind == "attempt_input")
    assert invalid_input.status == "unavailable" and invalid_input.original_ref
    assert next(entry for entry in entries if entry.original_ref == bad_tool).status == "unavailable"

    def storage_failed(**kwargs):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(store, "get_node_input_context", storage_failed)
    with pytest.raises(sqlite3.OperationalError):
        build_planning_context_catalog(runtime, final)


def test_workspace_material_is_frozen_readable_after_restart_and_catalog_reads_do_not_reindex_themselves(tmp_path):
    path = tmp_path / "workspace-catalog.sqlite3"
    store = SQLiteExecutionValueStore(db_path=path)
    evidence = EvidenceRun(store)
    evidence.commit({"path": "source.py", "text": "authenticated source body"}, step_id="discover",
        payload={"answer": "agent interpretation of source", "remaining": ["inspect caller"]})
    evidence.run.get_step("discover").logical_role = "workspace_discovery"
    evidence.run.execution_state["taskPlan"] = {"metadata": {"workspaceDiscovery": {
        "version": 1, "phase": "discovery", "scopeOrigin": "inferred"}}}
    mission = SimpleNamespace(title="Review repository", domain="general", intent="review")
    services = SimpleNamespace(execution_value_store=store,
        workflow_store=SimpleNamespace(get_mission=lambda _: mission))
    snapshot = workspace_discovery_snapshot(evidence.run, store)
    entries = build_planning_context_catalog(services, evidence.run, workspace_snapshot=snapshot)
    material = next(entry for entry in entries if entry.context_kind == "workspace_material")
    observation = RuntimePlanningObservation(missionId=evidence.run.mission_id, runId=evidence.run.run_id,
        graphId="graph", graphVersion=1, planVersion=1, wakeReason="resume", goal="Review repository",
        steps=(), remainingStepIds=(), workspaceDiscovery=snapshot, contextCatalog=entries)
    directory = read_planning_result_page(services, observation, catalog="contexts",
        context_kind="workspace_material", operation_id="find-workspace")
    assert directory["data"]["entries"][0]["contextRef"] == material.context_ref
    assert material.original_ref == snapshot["contextRef"]
    page = read_planning_result_page(services, observation, context_ref=material.context_ref,
        fields=["sources", "observations"], operation_id="workspace-body")
    assert page["data"]["sources"]["trustClass"] == "agent_generated"
    assert page["data"]["sources"]["content"][0]["findings"]["answer"] == "agent interpretation of source"
    following = read_planning_result_page(services, observation, context_ref=material.context_ref,
        fields=["sources", "observations"], cursor=page["nextCursor"], operation_id="workspace-observations")
    assert following["data"]["observations"]["trustClass"] == "verified_evidence"
    assert following["data"]["observations"]["content"][0]["output"]["text"] == "authenticated source body"
    assert following["nextCursor"] is None
    assert build_planning_context_catalog(services, evidence.run, workspace_snapshot=snapshot) == entries
    assert all(entry.step_id != "__planner_catalog__" for entry in entries)
    reopened = SimpleNamespace(execution_value_store=SQLiteExecutionValueStore(db_path=path))
    assert read_planning_result_page(reopened, observation, context_ref=material.context_ref,
        fields=["sources", "observations"], operation_id="workspace-body") == page


@pytest.mark.parametrize("tamper", ["owner", "kind", "alternate-slot", "changed-body"])
def test_context_reader_requires_the_original_owned_content_address(tmp_path, tamper):
    runtime, _, run = prepared(tmp_path)
    observation = runtime.runtime_planning_coordinator.observe(run, acg_execution_state_from_run(run), "resume")
    entry = next(item for item in observation.context_catalog if item.context_kind == "task_request")
    store = runtime.execution_value_store
    payload = store.get_output(run_id=run.run_id, output_ref=entry.context_ref)
    assert planning_context_reference(run.run_id, payload) == entry.context_ref
    assert store.get_tool_value(run_id=run.run_id, key=planning_context_key(payload)) == payload
    if tamper in {"owner", "kind"}:
        column, value = ("step_id", "another-step") if tamper == "owner" else ("kind", "context")
        with sqlite3.connect(store.db_path) as connection:
            connection.execute(f"UPDATE execution_values SET {column}=? WHERE reference=?", (value, entry.context_ref))
    elif tamper == "alternate-slot":
        reference = store.put_tool_value(run_id=run.run_id, step_id=PLANNING_CONTEXT_OWNER,
            key="unrelated-diagnostic-slot", payload=payload)
        entry = entry.model_copy(update={"context_ref": reference})
    else:
        payload["request"]["goal"] = "changed after sealing"
        with sqlite3.connect(store.db_path) as connection:
            connection.execute("UPDATE execution_values SET payload_json=? WHERE reference=?",
                (json.dumps(payload), entry.context_ref))
        entry = entry.model_copy(update={"checksum": stable_checksum(payload)})
    observation = observation.model_copy(update={"context_catalog": (entry,)})
    with pytest.raises(ValueError):
        read_planning_result_page(runtime, observation, context_ref=entry.context_ref,
            fields=["request"], operation_id="tampered-source")
