"""Retry context reuses only admitted, authenticated historical read results."""
import copy

import pytest

from contracts import stable_checksum
from contracts.workflow import StepStatus
from runtime.permit_recovery import (
    _settled_result_data, assert_native_readonly_retry_safe, settled_retry_observations,
)
from test_permit_readonly_recovery import _native_attempt, _replace_payload, store


def confirmed_read(store, *, tool="fs.read", terminal_status="failed"):
    services, run, node, *others = _native_attempt(store, missing_receipt=False,
        tool=tool, model_tool=tool.replace(".", "__"), terminal_status=terminal_status)
    operation = node.operation_id + ":tools:0:call:0"
    receipt = store.get_tool_value(run_id=run.run_id, key=operation + ":receipt")
    if tool == "fs.list":
        receipt["output"] = {"path": ".", "entries": [{"name": "source.py", "type": "file", "size": 25}]}
        receipt["checksum"] = stable_checksum({key: value for key, value in receipt.items() if key != "checksum"})
        _replace_payload(store, run.run_id, operation + ":receipt", receipt)
    cached = store.get_tool_value(run_id=run.run_id, key=operation + ":result")
    cached["record"].update(status="completed", receiptChecksum=receipt["checksum"])
    cached["data"] = _settled_result_data(receipt, cached["record"]["executionId"], tool)
    _replace_payload(store, run.run_id, operation + ":result", cached)
    return services, run, node, operation, cached, others


@pytest.mark.parametrize("tool", ["fs.read", "fs.list"])
@pytest.mark.parametrize("legacy_proof", [False, True])
@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_confirmed_reads_reach_the_new_attempt_with_original_identity(store, tool, legacy_proof, terminal_status):
    services, run, node, operation, cached, _ = confirmed_read(store, tool=tool, terminal_status=terminal_status)
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert len(proof["toolEvidence"]) == 1
    registered = copy.deepcopy(proof)
    if legacy_proof:
        registered.pop("toolEvidence")
    run.execution_state["readOnlyRetryProofs"] = {node.operation_id: registered}
    run.get_step(node.step_id).status = StepStatus.RUNNING
    run.get_step(node.step_id).attempt = 1
    before = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    observations = settled_retry_observations(services, run, node.step_id)
    assert len(observations) == 1
    previous = observations[0]
    assert previous["kind"] == "previous_attempt_tool_observation"
    assert previous["operationKey"] == operation
    assert previous["record"] == cached["record"]
    assert previous["result"] == cached["data"]
    assert previous["record"]["attemptId"] == node.attempt_id
    assert run.execution_state["readOnlyRetryProofs"][node.operation_id] == registered
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before
    assert run.completed_step_ids == []


@pytest.mark.parametrize("defect", ["missing_receipt", "missing_cache", "failed_receipt", "failed_record",
    "unmatched_projection", "unsettled"])
def test_repeatable_but_unconfirmed_or_failed_reads_never_supply_success_content(store, defect):
    services, run, node, operation, cached, _ = confirmed_read(store)
    if defect in {"missing_receipt", "missing_cache"}:
        suffixes = (":receipt", ":result") if defect == "missing_receipt" else (":result",)
        from runtime.permit_recovery import _tool_reference
        with store._connection:
            for suffix in suffixes:
                store._connection.execute("DELETE FROM execution_values WHERE reference=?",
                    (_tool_reference(run.run_id, operation + suffix),))
    elif defect == "failed_receipt":
        receipt = cached["data"]["handsReceipt"]
        receipt["status"] = "failed"
        receipt["checksum"] = stable_checksum({key: value for key, value in receipt.items() if key != "checksum"})
        _replace_payload(store, run.run_id, operation + ":receipt", receipt)
        cached["record"]["receiptChecksum"] = receipt["checksum"]
        _replace_payload(store, run.run_id, operation + ":result", cached)
    elif defect in {"failed_record", "unmatched_projection"}:
        if defect == "failed_record":
            cached["record"]["status"] = "failed"
        else:
            cached["data"]["content"] = "unverified content"
        _replace_payload(store, run.run_id, operation + ":result", cached)
    else:
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=operation + ":unsettled",
            payload={"runId": run.run_id, "stepId": node.step_id, "attemptId": node.attempt_id,
                "commitId": node.operation_id, "reason": "unconfirmed result"})
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["retrySafe"] is True and "toolEvidence" not in proof
    run.execution_state["readOnlyRetryProofs"] = {node.operation_id: proof}
    assert settled_retry_observations(services, run, node.step_id) == []


@pytest.mark.parametrize("tamper", ["proof", "result", "receipt"])
def test_retry_observations_revalidate_all_evidence_against_admitted_proof(store, tamper):
    services, run, node, operation, cached, _ = confirmed_read(store)
    proof = assert_native_readonly_retry_safe(services, run, node)
    run.execution_state["readOnlyRetryProofs"] = {node.operation_id: proof}
    if tamper == "proof":
        proof["evidenceFingerprint"] = "forged"
    elif tamper == "result":
        cached["data"]["content"] = "changed after admission"
        _replace_payload(store, run.run_id, operation + ":result", cached)
    else:
        receipt = cached["data"]["handsReceipt"]
        receipt["checksum"] = "changed after admission"
        _replace_payload(store, run.run_id, operation + ":receipt", receipt)
    with pytest.raises(ValueError, match="evidence changed|Hands receipt"):
        settled_retry_observations(services, run, node.step_id)


def test_retry_observations_do_not_include_other_nodes_proofs(store):
    services, run, node, *_ = confirmed_read(store)
    proof = assert_native_readonly_retry_safe(services, run, node)
    run.execution_state["readOnlyRetryProofs"] = {node.operation_id: proof}
    assert settled_retry_observations(services, run, "another-node") == []
