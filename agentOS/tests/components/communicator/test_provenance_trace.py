"""通信血缘向安全 Trace 投影的测试。"""

from __future__ import annotations

from components.communicator.provenance import ProvenanceLedger


def test_ledger_trace_projection_excludes_payload_body() -> None:
    """血缘 Trace 必须保留字段和校验和，但不得复制任何真实正文。"""
    ledger = ProvenanceLedger(run_id="run-1", task_id="task-1")
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
