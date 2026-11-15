"""通信血缘 SQLite 持久化与完整性校验测试。"""

from __future__ import annotations

import sqlite3

import pytest

from components.communicator.provenance import ProvenanceIntegrityError, ProvenanceLedger, provenance_checksum
from components.communicator.provenance_store import SQLiteProvenanceStore


def test_provenance_store_restores_hash_chain_and_event_sequence(tmp_path) -> None:
    """重启后应恢复同一 run 的哈希链，并从下一全局序号继续记账。"""
    db_path = tmp_path / "provenance.sqlite3"
    first_store = SQLiteProvenanceStore(db_path=db_path)
    first = ProvenanceLedger(
        run_id="run-a",
        mission_id="task-a",
        event_sink=first_store.append,
    )
    first.record_production("extract", {"title": "secret"}, 3)
    first_store.close()

    reopened_store = SQLiteProvenanceStore(db_path=db_path)
    restored = reopened_store.load_ledger(run_id="run-a", mission_id="task-a")
    restored.record_production("summarize", {"summary": "safe"}, 2)

    assert restored.verify_integrity() is True
    assert [item["payload"]["eventId"] for item in restored.trace_events()] == [
        "prod_000001",
        "prod_000002",
    ]
    reopened_store.close()


def test_provenance_store_rejects_tampered_persisted_event(tmp_path) -> None:
    """任一已持久化事件被篡改后，恢复必须拒绝而不能静默继续执行。"""
    db_path = tmp_path / "provenance.sqlite3"
    store = SQLiteProvenanceStore(db_path=db_path)
    ledger = ProvenanceLedger(
        run_id="run-a",
        mission_id="task-a",
        event_sink=store.append,
    )
    ledger.record_production("extract", {"title": "secret"}, 3)
    store.close()

    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE acg_provenance_events SET event_json = ? WHERE run_id = ?",
        ('{"eventId":"prod_000001","runId":"run-a","missionId":"task-a","previousHash":"","eventHash":"broken","producerStepId":"extract","fieldNames":["title"]}', "run-a"),
    )
    connection.commit()
    connection.close()

    reopened = SQLiteProvenanceStore(db_path=db_path)
    with pytest.raises(ProvenanceIntegrityError, match="integrity"):
        reopened.load_ledger(run_id="run-a", mission_id="task-a")
    reopened.close()


def test_ledger_restores_legacy_event_without_operation_id() -> None:
    """升级后的账本必须按旧字段重算历史事件哈希，不能因新增幂等字段拒绝续跑。"""
    legacy = {
        "eventId": "prod_000001",
        "runId": "run-a",
        "missionId": "task-a",
        "previousHash": "",
        "createdAt": "2026-01-01T00:00:00Z",
        "producerStepId": "extract",
        "agentName": "runner",
        "attempt": 1,
        "checksum": "output-checksum",
        "fieldNames": ["title"],
        "tokenSize": 1,
        "evidenceRefs": [],
    }
    legacy["eventHash"] = provenance_checksum(legacy)

    restored = ProvenanceLedger.from_events(
        run_id="run-a",
        mission_id="task-a",
        events=[legacy],
    )

    assert restored.verify_integrity() is True
    assert restored.productions[0].operation_id == ""
