"""Independent corruption checks for explicit, fully settled native retries."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from contracts import stable_checksum
from contracts.task_operator_policy import TaskOperatorPolicy
from components.executor.value_store import SQLiteExecutionValueStore
from runtime.permit_recovery import (
    _native_session_proof, _registered_settled_proof, operator_recovery_authorization, settled_retry_observations,
)
from test_permit_readonly_recovery import _native_attempt, _replace_payload


@pytest.fixture
def store(tmp_path):
    value_store = SQLiteExecutionValueStore(db_path=tmp_path / "audit-values.sqlite3")
    try:
        yield value_store
    finally:
        value_store.close()


def _key_ref(run, key):
    return "tool:" + hashlib.sha256((run.run_id + ":" + key).encode()).hexdigest()


def _settled_shell(store):
    services, run, node, *_ = _native_attempt(store, missing_receipt=False)
    turn_key = node.operation_id + ":tools:0"
    operation = turn_key + ":call:0"
    arguments = {"command": "echo fixture", "workdir": "."}
    model = store.get_tool_value(run_id=run.run_id, key=turn_key + ":model-turn")
    model["response"]["requestId"] = turn_key
    model["response"]["toolCalls"][0]["function"] = {
        "name": "shell__exec", "arguments": json.dumps(arguments)}
    _replace_payload(store, run.run_id, turn_key + ":model-turn", model)
    request = store.get_tool_value(run_id=run.run_id, key=operation + ":request")
    request["request"].update(capabilityId="shell.exec", input=arguments)
    _replace_payload(store, run.run_id, operation + ":request", request)
    receipt = store.get_tool_value(run_id=run.run_id, key=operation + ":receipt")
    receipt.update(capabilityId="shell.exec", output={
        "stdout": {"text": "fixture\n", "truncated": False},
        "stderr": {"text": "", "truncated": False}, "exitCode": 0})
    receipt["checksum"] = stable_checksum({key: value for key, value in receipt.items() if key != "checksum"})
    _replace_payload(store, run.run_id, operation + ":receipt", receipt)
    cached = store.get_tool_value(run_id=run.run_id, key=operation + ":result")
    cached["record"].update(tool="shell.exec", status="completed", receiptChecksum=receipt["checksum"])
    cached["data"] = {"stdout": "fixture\n", "stdoutTruncated": False,
        "stderr": "", "stderrTruncated": False, "exitCode": 0,
        "executionId": cached["record"]["executionId"], "receiptChecksum": receipt["checksum"],
        "handsReceipt": receipt, "status": "completed"}
    _replace_payload(store, run.run_id, operation + ":result", cached)
    auth = {"intent": "recover", "operationId": "explicit-recover", "requestFingerprint": "request-sha",
        "missionId": run.mission_id, "runId": run.run_id, "stepId": node.step_id,
        "policyRevision": 1, "actor": {"userId": "operator", "tenantId": "tenant"},
        "workspaceScope": {"workspaceId": "workspace", "grantId": "grant", "resourceId": "hands-resource"},
        "mayRepeatSettledActions": True}
    return services, run, node, operation, auth


def _proof(store, run, node, auth):
    return _native_session_proof(run, node, run.input["workspaceBinding"], store._connection,
        execution_value_store=store, settled_authorization=auth)


def test_confirmed_shell_can_be_proved_only_with_explicit_authorization(store):
    _, run, node, _, auth = _settled_shell(store)
    with pytest.raises(ValueError, match="write, shell or unknown"):
        _proof(store, run, node, None)
    proof = _proof(store, run, node, auth)
    assert proof["kind"] == "settled_native_session"
    assert proof["settledActionCount"] == 1 and proof["unconfirmedReadCount"] == 0
    assert proof["authorization"] == auth and proof["evidenceFingerprint"]


@pytest.mark.parametrize("suffix", [":receipt", ":result"])
def test_missing_result_or_receipt_blocks_shell_retry(store, suffix):
    _, run, node, operation, auth = _settled_shell(store)
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE reference=?", (_key_ref(run, operation + suffix),))
    with pytest.raises(ValueError):
        _proof(store, run, node, auth)


@pytest.mark.parametrize("defect", ["stdout", "status", "receiptChecksum", "identity", "grant", "resource", "kind"])
def test_tampered_result_data_record_or_ownership_is_rejected(store, defect):
    _, run, node, operation, auth = _settled_shell(store)
    cached = store.get_tool_value(run_id=run.run_id, key=operation + ":result")
    if defect == "stdout":
        cached["data"]["stdout"] = "forged evidence"
    elif defect == "status":
        cached["record"]["status"] = "failed"
    elif defect == "receiptChecksum":
        cached["record"]["receiptChecksum"] = "forged"
    elif defect == "identity":
        cached["record"]["attemptId"] = "other-attempt"
    elif defect == "grant":
        cached["record"]["grantId"] = "other-grant"
    elif defect == "resource":
        cached["record"]["resourceId"] = "other-runtime"
    elif defect == "kind":
        with store._connection:
            store._connection.execute("UPDATE execution_values SET kind='context' WHERE reference=?",
                (_key_ref(run, operation + ":result"),))
    if defect != "kind":
        _replace_payload(store, run.run_id, operation + ":result", cached)
    with pytest.raises(ValueError):
        _proof(store, run, node, auth)


def test_unsettled_marker_blocks_retry_even_with_completed_receipt(store):
    _, run, node, operation, auth = _settled_shell(store)
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=operation + ":unsettled",
        payload={"runId": run.run_id, "stepId": node.step_id, "attemptId": node.attempt_id,
            "commitId": node.operation_id, "reason": "external_outcome_unknown"})
    with pytest.raises(ValueError, match="unsettled"):
        _proof(store, run, node, auth)


def test_noncontiguous_hidden_model_turn_is_outside_proven_session_closure(store):
    _, run, node, _, auth = _settled_shell(store)
    source = store.get_tool_value(run_id=run.run_id, key=node.operation_id + ":tools:0:model-turn")
    key = node.operation_id + ":tools:2"
    hidden = copy.deepcopy(source)
    hidden["response"]["requestId"] = key
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key + ":model-turn", payload=hidden)
    with pytest.raises(ValueError, match="unexplained"):
        _proof(store, run, node, auth)


@pytest.mark.parametrize("tool,arguments", [
    ("context__list_sources", {}),
    ("context__read", {"producerStepId": "upstream", "fields": ["summary"]}),
    ("context__read_page", {"producerStepId": "upstream", "fields": ["summary"], "cursor": None, "pageTokens": 100}),
])
def test_known_context_reads_are_repeatable_without_external_dispatch_receipts(store, tool, arguments):
    _, run, node, _, auth = _settled_shell(store)
    key = node.operation_id + ":tools:1"
    response = store.get_tool_value(run_id=run.run_id, key=node.operation_id + ":tools:0:model-turn")
    response["response"].update(requestId=key, toolCalls=[{"id": "context", "type": "function",
        "function": {"name": tool, "arguments": json.dumps(arguments)}}])
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key + ":model-turn", payload=response)
    proof = _proof(store, run, node, auth)
    assert proof["modelTurnCount"] == 2 and proof["toolDeclarationCount"] == 2
    assert proof["settledActionCount"] == 1


@pytest.mark.parametrize("field,value", [("missionId", "other"), ("runId", "other"), ("stepId", "other"),
    ("operationId", ""), ("requestFingerprint", ""), ("intent", "dispatch"),
    ("mayRepeatSettledActions", False), ("policyRevision", True)])
def test_proof_rejects_unbound_or_implicit_authorization(store, field, value):
    _, run, node, _, auth = _settled_shell(store)
    auth[field] = value
    with pytest.raises(ValueError, match="operator authorization"):
        _proof(store, run, node, auth)


def _authority_services(policy):
    scope = {"workspaceId": "workspace", "grantId": "grant", "resourceId": "hands-resource"}
    run = SimpleNamespace(mission_id="mission", run_id="run", input={"workspaceBinding": scope})
    services = SimpleNamespace(
        workflow_store=SimpleNamespace(get_task_operator_policy=lambda _: policy),
        workspace_authority=SimpleNamespace(resolve=lambda _: SimpleNamespace(workspace_id="workspace", grant_id="grant")),
        semantic_principal_provider=lambda: SimpleNamespace(actor_id="user", tenant_id="tenant"))
    return services, run


@pytest.mark.parametrize("defect", ["ask", "other_workspace", "other_grant", "other_resource", "read_only"])
def test_current_full_policy_is_required_to_create_operator_recovery_authorization(defect):
    scope = {"workspaceId": "workspace", "grantId": "grant", "resourceId": "hands-resource"}
    changes = {"permission": "task_collaboration", "approvalMode": "full", "workspaceScope": scope}
    if defect == "ask":
        changes["approvalMode"] = "ask"
    elif defect == "read_only":
        changes.update(permission="read_only", approvalMode="ask")
    else:
        changes["workspaceScope"] = {**scope, {"other_workspace": "workspaceId", "other_grant": "grantId",
            "other_resource": "resourceId"}[defect]: "other"}
    policy = TaskOperatorPolicy(missionId="mission", policyRevision=1, **changes)
    services, run = _authority_services(policy)
    assert operator_recovery_authorization(services, run, "S2", "user-recover", "hash") is None


def test_full_policy_cannot_substitute_for_live_workspace_authority_or_explicit_intent():
    policy = TaskOperatorPolicy(missionId="mission", approvalMode="full", policyRevision=1,
        workspaceScope={"workspaceId": "workspace", "grantId": "grant", "resourceId": "hands-resource"})
    services, run = _authority_services(policy)
    assert operator_recovery_authorization(services, run, "S2", "user-recover", "hash")["intent"] == "recover"
    with pytest.raises(ValueError, match="explicit"):
        operator_recovery_authorization(services, run, "S2", "", "hash")
    services.workspace_authority.resolve = lambda _: SimpleNamespace(workspace_id="workspace", grant_id="revoked")
    with pytest.raises(ValueError, match="workspace authority"):
        operator_recovery_authorization(services, run, "S2", "user-recover", "hash")


def _register_authorization(store, run, node, auth):
    proof = _proof(store, run, node, auth)
    reference = store.put_tool_value(run_id=run.run_id, step_id=node.step_id,
        key=auth["operationId"] + ":settled-session-authorization",
        payload={"authorization": auth, "proofs": [{"operationId": node.operation_id,
            "evidenceFingerprint": proof["evidenceFingerprint"]}]})
    run.execution_state["inPlaceRetryRequests"] = {auth["operationId"]: auth["requestFingerprint"]}
    return {**proof, "authorizationRef": reference}


def test_stored_authorization_requires_immutable_matching_admission_not_only_run_state(store):
    services, run, node, _, auth = _settled_shell(store)
    proof = _register_authorization(store, run, node, auth)
    assert _registered_settled_proof(services, run, node, proof, connection=store._connection) == proof
    forged = copy.deepcopy(proof)
    forged["authorization"]["actor"]["userId"] = "other-user"
    with pytest.raises(ValueError, match="immutable operator receipt"):
        _registered_settled_proof(services, run, node, forged, connection=store._connection)
    run.execution_state["inPlaceRetryRequests"][auth["operationId"]] = "other-fingerprint"
    with pytest.raises(ValueError, match="admitted operator request"):
        _registered_settled_proof(services, run, node, proof, connection=store._connection)


def test_stored_proof_cannot_be_recreated_from_policy_fields_after_immutable_receipt_loss(store):
    services, run, node, _, auth = _settled_shell(store)
    proof = _register_authorization(store, run, node, auth)
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE reference=?", (proof["authorizationRef"],))
    with pytest.raises(ValueError, match="immutable operator receipt"):
        _registered_settled_proof(services, run, node, proof, connection=store._connection)


def test_current_artifact_hash_is_rechecked_before_old_observations_are_reused(store):
    services, run, node, operation, auth = _settled_shell(store)
    proof = _register_authorization(store, run, node, auth)
    cached = store.get_tool_value(run_id=run.run_id, key=operation + ":result")
    cached["data"]["stdout"] = "modified after recovery admission"
    _replace_payload(store, run.run_id, operation + ":result", cached)
    with pytest.raises(ValueError):
        _registered_settled_proof(services, run, node, proof, connection=store._connection)


def test_historical_observations_remain_old_attempt_evidence_while_new_attempt_is_active(store):
    services, run, node, operation, auth = _settled_shell(store)
    proof = _register_authorization(store, run, node, auth)
    run.execution_state["settledSessionRetryProofs"] = {node.operation_id: proof}
    new = node.model_copy(update={"operation_id": "new-active-operation", "attempt_id": "new-attempt",
        "execution_instance_id": "new-generation:run:S2:1:root"})
    store.prepare_node_commit(run_id=run.run_id, commit_id=new.operation_id)
    store.transition_node_execution(new)
    run.execution_state["executionGeneration"] = "new-generation"
    run.execution_state["activeStepIds"] = [node.step_id]
    run.get_step(node.step_id).status = "running"
    previous = store.get_tool_value(run_id=run.run_id, key=operation + ":result")
    observations = settled_retry_observations(services, run, node.step_id)
    assert len(observations) == 1
    assert observations[0]["kind"] == "previous_attempt_tool_observation"
    assert observations[0]["record"]["attemptId"] == node.attempt_id
    assert observations[0]["record"]["commitId"] == node.operation_id
    assert observations[0]["result"] == previous["data"]
    assert store.get_tool_value(run_id=run.run_id, key=operation + ":result") == previous
    assert store.get_node_commit(run_id=run.run_id, commit_id=new.operation_id)["stage"] == "prepared"
