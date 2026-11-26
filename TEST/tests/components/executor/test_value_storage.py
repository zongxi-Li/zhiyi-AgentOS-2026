from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from components.executor.value_store import SQLiteExecutionValueStore, ExecutionValueAccessError
from components.executor.value_storage import body_path, decode_body, migrate


def test_large_tool_bodies_reopen_deduplicate_and_keep_independent_receipts(tmp_path):
    database = tmp_path / "values.sqlite3"
    store = SQLiteExecutionValueStore(db_path=database)
    payload = {"encoding": "base64", "content": "A" * 300000}
    first = store.put_tool_value(run_id="run", step_id="step", key="call1:receipt", payload=payload)
    second = store.put_tool_value(run_id="run", step_id="step", key="call2:receipt", payload=payload)
    assert first != second
    rows = store._connection.execute("SELECT content_ref,byte_length FROM execution_value_storage").fetchall()
    assert rows[0][0] == rows[1][0]
    assert len(list(database.with_suffix(".bodies").glob("*/*"))) == 2
    assert max(len(row[0]) for row in store._connection.execute("SELECT payload_json FROM execution_values")) < 1000
    report = store.storage_usage(run_id="run", since=datetime.now(timezone.utc)-timedelta(days=1))
    assert report["logicalBytes"] == sum(row[1] for row in rows)
    assert report["duplicatePayloadBytes"] == rows[0][1]
    assert report["growthBytes"] == report["logicalBytes"]
    assert report["encodedBinaryBytes"] == 600000
    assert report["largestRecord"]["reference"] in {first, second}
    store.close()
    store = SQLiteExecutionValueStore(db_path=database)
    assert store.get_tool_value(run_id="run", key="call1:receipt") == payload
    with pytest.raises(ExecutionValueAccessError):
        store.get_output(run_id="other", output_ref=first)
    path = body_path(store._connection, rows[0][0])
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        store.get_tool_value(run_id="run", key="call2:receipt")
    store.close()


def test_legacy_metadata_backfill_is_bounded_and_query_plans_search_run_indexes(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    payload = {"body": "legacy" * 50000}
    for index in range(3):
        store._connection.execute("""INSERT INTO execution_values
            (reference,run_id,step_id,kind,payload_json,created_at,operation_id) VALUES(?,?,?,?,?,?,NULL)""",
            (f"output:old:{index}", "run", "step", "output", json.dumps(payload), 1.0))
    store._connection.commit()
    assert store.storage_usage(run_id="run")["unmeasuredRecords"] == 3
    assert migrate(store._connection, run_id="run", limit=2) == 2
    assert store.storage_usage(run_id="run")["unmeasuredRecords"] == 1
    assert store.get_output(run_id="run", output_ref="output:old:0") == payload
    assert migrate(store._connection, run_id="run", limit=2) == 1
    assert migrate(store._connection, run_id="run", limit=2) == 0
    for sql, args in [
        ("SELECT reference,run_id,step_id,kind,created_at FROM execution_values WHERE run_id=? AND created_at<? ORDER BY reference", ("run", 100)),
        ("SELECT reference,step_id,created_at FROM execution_values WHERE run_id=? AND kind='output' AND reference GLOB 'tool:*' ORDER BY reference", ("run",)),
        ("SELECT payload_json,created_at FROM execution_values WHERE run_id=? AND reference LIKE 'tool:%' AND json_type(payload_json,'$.record.executionId')='text' ORDER BY created_at DESC LIMIT 100", ("run",)),
        ("SELECT payload_json FROM execution_values WHERE run_id=? AND step_id=? AND reference LIKE 'tool:%' AND json_type(payload_json,'$.requestHash') IS NOT NULL", ("run", "step")),
        ("SELECT operation_id,payload_json FROM acg_node_executions WHERE run_id=? ORDER BY operation_id", ("run",)),
    ]:
        plan = " ".join(str(row[3]) for row in store._connection.execute("EXPLAIN QUERY PLAN " + sql, args))
        assert "SEARCH" in plan and "INDEX" in plan
        assert "SCAN " not in plan
    store.close()


def test_archival_preserves_reads_and_pins_veto_deletion_and_blob_collection(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    refs = [store.put_output(run_id="run", step_id="step", payload={"body": "x"*300000}) for _ in range(2)]
    store.transition_storage(run_id="run", references=refs, state="archived", terminal=True)
    assert store.get_output(run_id="run", output_ref=refs[0])["body"] == "x"*300000
    with pytest.raises(ValueError, match="protected"):
        store.transition_storage(run_id="run", references=refs, state="deletable", terminal=False)
    with pytest.raises(ValueError, match="protected"):
        store.transition_storage(run_id="run", references=refs, state="deletable", terminal=True, protected_refs={refs[1]})
    store.pin_body(run_id="run", reference=refs[0], owner="memory:fact")
    assert store.delete_references(run_id="run", references=refs) == 1
    assert store.collect_body_files() == 0
    store.pin_body(run_id="run", reference=refs[0], owner="memory:fact", enabled=False)
    store.transition_storage(run_id="run", references=refs[:1], state="archived", terminal=True)
    store.transition_storage(run_id="run", references=refs[:1], state="deletable", terminal=True)
    assert store.delete_references(run_id="run", references=refs[:1]) == 1
    assert store.collect_body_files() == 2
    store.close()


def test_same_file_body_deduplicates_across_distinct_receipt_identities(tmp_path):
    from components.executor.value_storage import BODY_MAGIC
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    for key in ("read1", "read2"):
        payload = {"response": {"requestId": key}, "output": {"content": "same source\n"*40000}}
        store.put_tool_value(run_id="run", step_id="step", key=key, payload=payload)
    refs = store._connection.execute("SELECT content_ref FROM execution_value_storage").fetchall()
    assert refs[0][0] != refs[1][0]
    manifests = [json.loads(body_path(store._connection, row[0]).read_bytes()[len(BODY_MAGIC):]) for row in refs]
    assert manifests[0]["parts"][0]["ref"] == manifests[1]["parts"][0]["ref"]
    assert store.get_tool_value(run_id="run", key="read1")["response"]["requestId"] == "read1"
    assert store.get_tool_value(run_id="run", key="read2")["response"]["requestId"] == "read2"
    store.close()


def test_external_tool_requests_keep_sql_identity_but_decode_complete_body(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    payload = {"request": {"capabilityId": "fs.write", "invocationId": "commit:0",
        "arguments": {"content": "x"*300000}}, "identity": {"runId": "run", "stepId": "step"}}
    ref = store.put_tool_value(run_id="run", step_id="step", key="req", payload=payload)
    row = store._connection.execute("SELECT payload_json FROM execution_values WHERE reference=?", (ref,)).fetchone()
    assert json.loads(row[0])["request"]["invocationId"] == "commit:0"
    assert decode_body(store._connection, run_id="run", reference=ref, encoded=row[0]) == payload
    with pytest.raises(ValueError, match="another Run"):
        decode_body(store._connection, run_id="other", reference=ref, encoded=row[0])
    store.close()
