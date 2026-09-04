"""通信血缘向安全 Trace 投影的测试。"""

from __future__ import annotations

import pytest

from components.communicator import CommunicatorService
from components.communicator.provenance import ProvenanceIntegrityError, ProvenanceLedger


def test_ledger_trace_projection_excludes_payload_body() -> None:
    """血缘 Trace 必须保留字段和校验和，但不得复制任何真实正文。"""
    ledger = ProvenanceLedger(run_id="run-1", mission_id="task-1")
    ledger.record_production("extract", {"title": "AgentOS secret"}, 5)
    ledger.record_consumption(
        "summarize",
        ["extract"],
        ["title"],
        fields_by_producer={"extract": ["title"]},
        data={"title": "AgentOS secret"},
        tokens_delivered=3,
        tokens_available=5,
        saving_ratio=0.4,
    )

    events = ledger.trace_events()

    assert [item["eventType"] for item in events] == ["data_produced", "data_consumed"]
    assert events[0]["payload"]["fieldNames"] == ["title"]
    assert events[1]["payload"]["consumedFields"] == ["title"]
    assert "AgentOS secret" not in str(events)
    assert "title" not in str(events[0]["payload"].get("checksum", ""))


def test_service_drains_provenance_events_by_step_ownership() -> None:
    """并行步骤交错记账时，每个节点只能领取归属自己的生产或消费事件。"""
    service = CommunicatorService(run_id="run-1", mission_id="task-1")
    service.record_production("left", {"left": "secret-left"})
    service.record_production("right", {"right": "secret-right"})

    left_events = service.drain_provenance_events(step_id="left")
    right_events = service.drain_provenance_events(step_id="right")

    assert [item["payload"]["producerStepId"] for item in left_events] == ["left"]
    assert [item["payload"]["producerStepId"] for item in right_events] == ["right"]


def test_ledger_rejects_event_reference_owned_by_another_step() -> None:
    """恢复的 provenanceRefs 只能指向当前步骤生产或消费的真实账本事件。"""
    ledger = ProvenanceLedger(run_id="run-1", mission_id="task-1")
    event = ledger.record_production("extract", {"title": "safe"}, 1)

    ledger.assert_event_owner(event_id=event.event_id, step_id="extract")
    with pytest.raises(ProvenanceIntegrityError, match="does not belong to step summarize"):
        ledger.assert_event_owner(event_id=event.event_id, step_id="summarize")
    with pytest.raises(ProvenanceIntegrityError, match="does not exist"):
        ledger.assert_event_owner(event_id="prod_999999", step_id="extract")


def test_ledger_reuses_same_commit_production_without_appending_event() -> None:
    """节点在提交前异常重试时，同一 commitId 的血缘只能保留一条不可变事件。"""
    ledger = ProvenanceLedger(run_id="run-1", mission_id="task-1")

    first = ledger.record_production(
        "extract",
        {"title": "safe"},
        1,
        operation_id="commit:run-1:extract:0",
    )
    repeated = ledger.record_production(
        "extract",
        {"title": "safe"},
        1,
        operation_id="commit:run-1:extract:0",
    )

    assert repeated.event_id == first.event_id
    assert len(ledger.productions) == 1
    with pytest.raises(ProvenanceIntegrityError, match="different payload"):
        ledger.record_production(
            "extract",
            {"title": "changed"},
            1,
            operation_id="commit:run-1:extract:0",
        )
