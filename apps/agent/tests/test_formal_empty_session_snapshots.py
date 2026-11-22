"""Derived Planner contexts must not look like newly admitted native work."""
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from contracts.planning_context import PLANNING_CONTEXT_OWNER
from contracts import stable_checksum
from contracts.execution_guidance import ExecutionGuidance, execution_guidance_key
from runtime.orchestration.planning_context_catalog import build_planning_context_catalog
from tests.test_formal_tool_recovery import _seed_memory_input, session  # noqa: F401


@pytest.fixture
def empty_session_snapshot(session):
    services, run, node, _, runtime, tools = session
    store = runtime.execution_value_store
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE run_id=?", (run.run_id,))
    _seed_memory_input(store, run, node, with_record=True)
    services.workflow_store = SimpleNamespace(get_mission=lambda _: SimpleNamespace(
        title="Review saved context", domain="general", intent="review"))
    entries = build_planning_context_catalog(services, run)
    memory = next(entry for entry in entries if entry.context_kind == "memory_retrieval")
    assert store.get_output(run_id=run.run_id, output_ref=memory.context_ref)["identity"]["commitId"] == node.operation_id
    return run, node, store, tools, memory


def prove_empty_session(run, node, store, tools):
    with sqlite3.connect(store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        return tools.prove_not_dispatched(run=run, node=node, operation=node.operation_id,
            tool="native.tool-session", raw_arguments=None, workspace=run.input["workspaceBinding"],
            connection=connection, execution_value_store=store)


def test_real_catalog_snapshot_does_not_change_empty_session_admission_or_write_anything(empty_session_snapshot):
    run, node, store, tools, _ = empty_session_snapshot
    before = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    proof = prove_empty_session(run, node, store, tools)
    assert proof["dispatched"] is False and proof["identity"]["commitId"] == node.operation_id
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before


@pytest.mark.parametrize("damage", ["owner", "kind", "operation", "metadata", "reference", "source-run"])
def test_only_the_owned_exactly_sealed_snapshot_is_exempt_from_execution_closure(empty_session_snapshot, damage):
    run, node, store, tools, entry = empty_session_snapshot
    if damage in {"owner", "kind", "operation"}:
        column, value = {"owner": ("step_id", "other-step"), "kind": ("kind", "context"),
            "operation": ("operation_id", "external-operation")}[damage]
        with store._connection:
            store._connection.execute(f"UPDATE execution_values SET {column}=? WHERE reference=?",
                (value, entry.context_ref))
    else:
        payload = store.get_output(run_id=run.run_id, output_ref=entry.context_ref)
        if damage == "reference":
            store.put_tool_value(run_id=run.run_id, step_id=PLANNING_CONTEXT_OWNER,
                key="unsealed-copy", payload=payload)
        else:
            if damage == "metadata":
                payload["__planning_context__"].pop("trust")
            else:
                payload["__planning_context__"]["sourceRunId"] = "another-run"
            with store._connection:
                store._connection.execute("UPDATE execution_values SET payload_json=? WHERE reference=?",
                    (json.dumps(payload), entry.context_ref))
    with pytest.raises(ValueError, match="admitted model or tool work"):
        prove_empty_session(run, node, store, tools)


@pytest.mark.parametrize("owner", ["S2", PLANNING_CONTEXT_OWNER])
def test_valid_snapshots_cannot_hide_a_real_request_under_any_ledger_owner(empty_session_snapshot, owner):
    run, node, store, tools, entry = empty_session_snapshot
    original = store.get_output(run_id=run.run_id, output_ref=entry.context_ref)
    request = {"request": {"invocationId": node.operation_id + ":tools:0:call:0"},
        "__planning_context__": deepcopy(original["__planning_context__"])}
    store.put_tool_value(run_id=run.run_id, step_id=owner,
        key=node.operation_id + ":tools:0:call:0:request", payload=request)
    with pytest.raises(ValueError, match="admitted model or tool work"):
        prove_empty_session(run, node, store, tools)


def seed_guidance_inputs(run, node, store):
    guidance = ExecutionGuidance(runId=run.run_id, stepId=node.step_id, userInputs=({
        "sourceRunId": run.run_id, "operationId": "confirmed-input", "content": "Deliver existing evidence",
        "submittedAt": "2026-11-19T09:32:05Z"},)).model_dump(by_alias=True, mode="json", exclude_none=True)
    initial = {"version": 1, "runId": run.run_id, "stepId": node.step_id, "commitId": node.operation_id,
        "guidance": guidance, "guidanceHash": stable_checksum(guidance)}
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=execution_guidance_key(node.operation_id), payload=initial)
    message = json.dumps({"requestType": "ExecutionGuidanceUpdate", "instructions": "archived policy", "guidance": guidance})
    receipt = {"version": "session-execution-guidance.v1", "runId": run.run_id, "stepId": node.step_id,
        "commitId": node.operation_id, "turn": 0, "baseMessagesHash": "a" * 64,
        "previousGuidanceHash": None, "guidance": guidance, "guidanceHash": stable_checksum(guidance),
        "message": message, "messageHash": stable_checksum(message)}
    key = node.operation_id + ":tools:0:execution-guidance:v1"
    ref = store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=receipt)
    return key, ref, receipt


def test_sealed_guidance_before_first_model_response_is_internal_input(empty_session_snapshot):
    run, node, store, tools, _ = empty_session_snapshot
    seed_guidance_inputs(run, node, store)
    before = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    assert prove_empty_session(run, node, store, tools)["dispatched"] is False
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before


@pytest.mark.parametrize("damage", ["owner", "kind", "operation", "hash", "extra_request", "wrong_address", "future_turn"])
def test_guidance_cannot_hide_unowned_unsealed_or_external_activity(empty_session_snapshot, damage):
    run, node, store, tools, _ = empty_session_snapshot
    key, ref, payload = seed_guidance_inputs(run, node, store)
    if damage in {"owner", "kind", "operation"}:
        column, value = {"owner": ("step_id", "other"), "kind": ("kind", "context"),
            "operation": ("operation_id", "external")}[damage]
        with store._connection:
            store._connection.execute(f"UPDATE execution_values SET {column}=? WHERE reference=?", (value, ref))
    elif damage in {"wrong_address", "future_turn"}:
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id,
            key=key + ":copy" if damage == "wrong_address" else node.operation_id + ":tools:1:execution-guidance:v1",
            payload=payload)
    else:
        if damage == "hash": payload["guidanceHash"] = "b" * 64
        else: payload["request"] = {"invocationId": node.operation_id + ":tools:0:call:0"}
        with store._connection:
            store._connection.execute("UPDATE execution_values SET payload_json=? WHERE reference=?", (json.dumps(payload), ref))
    with pytest.raises(ValueError):
        prove_empty_session(run, node, store, tools)
