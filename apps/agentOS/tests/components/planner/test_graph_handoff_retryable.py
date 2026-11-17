"""Only temporary execution-fence contention automatically retries handoff."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from contracts.graph_handoff import GraphHandoffReceipt
from runtime import graph_handoff
from support.run_execution_fence import RunFenceBusy


@pytest.mark.parametrize("busy", [False, True])
def test_only_run_fence_contention_is_marked_retryable(monkeypatch, busy):
    authority = object.__new__(graph_handoff.GraphHandoffAuthority)
    authority.store = SimpleNamespace(db_path="unused", get_activation=lambda _: SimpleNamespace(run_id="run-test"))
    authority.runtime = SimpleNamespace(run_lock_manager=SimpleNamespace(lock_for=lambda _: nullcontext()))

    def acquire(*args):
        if busy:
            raise RunFenceBusy("occupied")
        return nullcontext()

    def validate(*args):
        raise graph_handoff.HandoffEvidenceError("unresolved control cannot be handed off")

    authority._validated_candidate = validate
    monkeypatch.setattr(graph_handoff, "acquire_run_fence", acquire)
    receipt = authority.prepare("activation:test", idempotency_key="handoff:test")
    assert receipt.status == "REJECTED" and receipt.retryable is busy
    if busy:
        assert receipt.code == "CONTROL_BARRIER_BLOCKED"
        assert receipt.model_dump(by_alias=True)["retryable"] is True
    else:
        assert "retryable" not in receipt.model_dump(by_alias=True)


def test_default_retry_marker_preserves_historical_receipt_wire_shape():
    receipt = GraphHandoffReceipt(status="STATE_PREPARED", handoffId="handoff:test")
    assert "retryable" not in receipt.model_dump(by_alias=True)
    assert not GraphHandoffReceipt.model_validate_json(receipt.model_dump_json()).retryable
