"""Guidance is authenticated internal input, never unexplained external work."""
import hashlib
import json

import pytest

from contracts import stable_checksum
from contracts.capability import ModelInvocationResponse
from contracts.execution_guidance import ExecutionGuidance, execution_guidance_key
from runtime.orchestration.permit_recovery import _readonly_session_proof, assert_native_readonly_retry_safe
from TEST.tests.runtime.test_permit_readonly_recovery import _empty_native_attempt, _replace_payload, _seed, store  # noqa: F401


def reference(run_id, key):
    return "tool:" + hashlib.sha256((run_id + ":" + key).encode()).hexdigest()


def guidance(run, node, content="Deliver existing evidence", operation="input:1"):
    return ExecutionGuidance(runId=run.run_id, stepId=node.step_id, userInputs=({
        "sourceRunId": run.run_id, "operationId": operation, "content": content,
        "submittedAt": "2026-11-19T09:32:05Z"},)).model_dump(by_alias=True, mode="json", exclude_none=True)


def initial(store, run, node, value):
    key = execution_guidance_key(node.operation_id)
    payload = {"version": 1, "runId": run.run_id, "stepId": node.step_id, "commitId": node.operation_id,
               "guidance": value, "guidanceHash": stable_checksum(value)}
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=payload)
    return key, payload


def delivery(store, run, node, turn, value, previous=None):
    key = f"{node.operation_id}:tools:{turn}:execution-guidance:v1"
    current = stable_checksum(value) if value is not None else previous
    message = json.dumps({"requestType": "ExecutionGuidanceUpdate", "instructions": "archived policy v1",
        "guidance": value}) if value is not None and current != previous else None
    payload = {"version": "session-execution-guidance.v1", "runId": run.run_id, "stepId": node.step_id,
        "commitId": node.operation_id, "turn": turn, "baseMessagesHash": "b" * 64,
        "previousGuidanceHash": previous, "guidance": value, "guidanceHash": current,
        "message": message, "messageHash": stable_checksum(message)}
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=payload)
    return key, payload


def completion(store, run, node, turn, value, delivered, candidate):
    key = f"{node.operation_id}:tools:{turn}:guidance-completion:v1"
    current = stable_checksum(value) if value is not None else None
    feedback = "Reconcile with the new confirmed request" if value is not None and current != delivered else None
    payload = {"version": "session-execution-guidance.v1", "runId": run.run_id, "stepId": node.step_id,
        "commitId": node.operation_id, "turn": turn, "deliveredGuidanceHash": delivered,
        "candidateHash": stable_checksum(candidate), "currentGuidance": value,
        "currentGuidanceHash": current, "feedback": feedback, "feedbackHash": stable_checksum(feedback)}
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=payload)
    return key, payload


def proof(store, run, node):
    return _readonly_session_proof(run, node,
        {"workspaceId": "workspace", "grantId": "grant"}, store._connection)


def test_internal_initial_delivery_and_pre_response_tail_are_included_in_recovery_digest(store):
    run, node = _seed(store)
    before = proof(store, run, node)
    value = guidance(run, node)
    initial(store, run, node, value)
    delivery(store, run, node, 0, value)
    first = proof(store, run, node)
    delivery(store, run, node, 1, guidance(run, node, "Finish now", "input:2"), stable_checksum(value))
    frozen = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    pending = proof(store, run, node)
    assert before["evidenceFingerprint"] != first["evidenceFingerprint"] != pending["evidenceFingerprint"]
    assert pending["modelTurnCount"] == 1 and pending["confirmedReadCount"] == 1
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == frozen


def test_delivery_before_first_response_remains_internal_but_requires_no_dispatch_proof(store):
    services, run, node, *_ = _empty_native_attempt(store)
    value = guidance(run, node)
    initial(store, run, node, value)
    delivery(store, run, node, 0, value)
    result = assert_native_readonly_retry_safe(services, run, node)
    assert result["kind"] == "native_session_not_dispatched"
    assert result["modelTurnCount"] == result["toolDeclarationCount"] == 0
    services.tool_non_invocation_prover = None
    with pytest.raises(ValueError, match="trusted no-dispatch"):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("damage", ["run", "owner", "kind", "operation", "address", "version", "hash", "extra"])
@pytest.mark.parametrize("slot", ["initial", "delivery"])
def test_internal_guidance_requires_exact_ledger_slot_owner_and_sealed_payload(store, slot, damage):
    run, node = _seed(store)
    value = guidance(run, node)
    key, payload = initial(store, run, node, value) if slot == "initial" else delivery(store, run, node, 0, value)
    ref = reference(run.run_id, key)
    if damage in {"run", "owner", "kind", "operation"}:
        column, changed = {"run": ("run_id", "other-run"), "owner": ("step_id", "other"), "kind": ("kind", "context"),
                           "operation": ("operation_id", "external")}[damage]
        with store._connection:
            store._connection.execute(f"UPDATE execution_values SET {column}=? WHERE reference=?", (changed, ref))
    elif damage == "address":
        with store._connection:
            store._connection.execute("DELETE FROM execution_values WHERE reference=?", (ref,))
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key + ":forged", payload=payload)
    else:
        if damage == "version": payload["version"] = True
        elif damage == "hash": payload["guidanceHash"] = "a" * 64
        else: payload["request"] = {"invocationId": node.operation_id + ":tools:0:call:1"}
        _replace_payload(store, run.run_id, key, payload)
    with pytest.raises(ValueError):
        proof(store, run, node)


@pytest.mark.parametrize("damage", ["chain", "turn_type", "message", "message_hash", "hidden_turn"])
def test_delivery_chain_and_archived_message_cannot_be_substituted(store, damage):
    run, node = _seed(store)
    key, payload = delivery(store, run, node, 0, guidance(run, node))
    if damage == "chain": payload["previousGuidanceHash"] = "a" * 64
    elif damage == "turn_type": payload["turn"] = False
    elif damage == "message":
        body = json.loads(payload["message"])
        body["guidance"]["userInputs"][0]["content"] = "Substituted user instruction"
        payload["message"] = json.dumps(body)
        payload["messageHash"] = stable_checksum(payload["message"])
    elif damage == "message_hash": payload["messageHash"] = "a" * 64
    else:
        delivery(store, run, node, 7, guidance(run, node), payload["guidanceHash"])
    _replace_payload(store, run.run_id, key, payload)
    with pytest.raises(ValueError):
        proof(store, run, node)


@pytest.mark.parametrize("damage", [None, "candidate", "feedback", "chain", "unanswered"])
def test_completion_race_receipt_binds_the_frozen_final_candidate_and_delivered_guidance(store, damage):
    services, run, node, *_ = _empty_native_attempt(store)
    candidate = {"answer": "report based on existing evidence"}
    response = ModelInvocationResponse(requestId=node.operation_id + ":tools:0", content=candidate,
        provider="test", model="mock")
    if damage != "unanswered":
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id,
            key=node.operation_id + ":tools:0:model-turn", payload={"requestHash": "a" * 64,
                "response": response.model_dump(by_alias=True, mode="json")})
    value = guidance(run, node)
    delivery(store, run, node, 0, value)
    key, payload = completion(store, run, node, 0, guidance(run, node, "Finish now", "input:2"),
        stable_checksum(value), candidate)
    if damage == "candidate": payload["candidateHash"] = stable_checksum({"answer": "other"})
    elif damage == "feedback":
        payload["feedback"] = None
        payload["feedbackHash"] = stable_checksum(None)
    elif damage == "chain": payload["deliveredGuidanceHash"] = None
    _replace_payload(store, run.run_id, key, payload)
    if damage:
        with pytest.raises(ValueError, match="execution guidance"):
            assert_native_readonly_retry_safe(services, run, node)
    else:
        result = assert_native_readonly_retry_safe(services, run, node)
        assert result["modelTurnCount"] == 1 and result["toolDeclarationCount"] == 0


def test_authenticated_guidance_never_exempts_a_shell_declaration_from_reconciliation(store):
    run, node = _seed(store, tool="shell.exec", model_tool="shell__exec")
    initial(store, run, node, guidance(run, node))
    delivery(store, run, node, 0, guidance(run, node))
    with pytest.raises(ValueError, match="write, shell or unknown"):
        proof(store, run, node)
