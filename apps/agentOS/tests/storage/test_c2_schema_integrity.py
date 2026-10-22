"""Missing evidence is corruption, not an incomplete Schema installation."""
from pathlib import Path
import sys

import pytest

from contracts import stable_checksum
from support.stores import c2_schema_upgrade as ops
from test_c2_schema_upgrade import contents, sql, base, paths

# Reuse the real accepted revision / activation / handoff SQLite seed. It
# contains an actually executed A and no invented Receipt or Permit payload.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "components" / "planner"))
from test_execution_permit import ready_handoff


def database_paths(ready):
    rt, workflow = ready[:2]
    return dict(workflow=workflow.db_path.resolve(), checkpoint=rt.checkpoint_store.db_path.resolve(),
                identity=Path(rt.identity_lifecycle.repositories.storage.db_path).resolve())


@pytest.mark.parametrize("damage,affected", [
    ("handoff_table", "workflow"), ("handoff_table_empty_permit", "workflow"),
    ("stage_table_handoff", "checkpoint"), ("stage_table_permit", "checkpoint"),
    ("handoff_row", "workflow"), ("stage_row", "checkpoint"),
    ("stage_table_staging", "checkpoint"), ("permit_table", "workflow"), ("stage_checksum", "checkpoint"),
])
def test_dependent_real_records_cannot_be_replaced_with_empty_schema(ready_handoff, damage, affected):
    rt, _, _, _, _, handoffs, stages, permits, handoff_id = ready_handoff
    handoff = handoffs.get_handoff(handoff_id)
    assert handoff.status == "STATE_PREPARED" and stages.get(handoff.candidate.checkpoint_id) == handoff.candidate
    if damage in {"handoff_table", "stage_table_permit", "handoff_row", "permit_table"}:
        receipt = rt.issue_execution_permit(handoff_id, idempotency_key="integrity-proof")
        assert receipt.status == "ISSUED", receipt
        assert permits.get_permit(receipt.permit_id).handoff_id == handoff_id
    dbs = database_paths(ready_handoff)
    assert {v["status"] for v in ops.inspect_databases(**dbs).values()} == {"READY"}
    if damage == "stage_table_staging":
        intent = handoff.model_copy(update={"status": "STAGING"})
        sql(dbs["workflow"], "UPDATE graph_handoffs SET status=?,payload=?,checksum=? WHERE handoff_id=?",
            (intent.status, intent.model_dump_json(by_alias=True), stable_checksum(intent), handoff_id))
    if damage.startswith("handoff_table"):
        sql(dbs["workflow"], "DROP TABLE graph_handoffs")
    elif damage.startswith("stage_table"):
        sql(dbs["checkpoint"], "DROP TABLE staged_graph_checkpoints")
    elif damage == "handoff_row":
        sql(dbs["workflow"], "DELETE FROM graph_handoffs WHERE handoff_id=?", (handoff_id,))
    elif damage == "permit_table":
        sql(dbs["workflow"], "DROP TABLE graph_execution_permits")
        sql(dbs["workflow"], "DROP TABLE graph_execution_permit_schema")
    elif damage == "stage_checksum":
        sql(dbs["checkpoint"], "UPDATE staged_graph_checkpoints SET checksum=?", ("0" * 64,))
    else:
        sql(dbs["checkpoint"], "DELETE FROM staged_graph_checkpoints WHERE checkpoint_id=?", (handoff.candidate.checkpoint_id,))
    before = contents(dbs)
    inspection = ops.inspect_databases(**dbs)
    assert inspection[affected]["status"] == "INVALID", inspection
    assert "error" in inspection[affected]
    with pytest.raises(ops.SchemaUpgradeError, match="preflight rejected"):
        ops.upgrade_databases(**dbs)
    assert contents(dbs) == before  # full DDL, indexes, triggers and rows in all three files


def test_empty_installation_can_resume_missing_handoff_and_stage(paths):
    base(paths)
    # Genuine installer cut: Activation installed, Handoff/Permit not started.
    for factory in ops.UPGRADERS[:3]:
        factory.upgrade_schema(paths["workflow"])
    state = ops.inspect_databases(**paths)
    assert state["workflow"]["status"] == state["checkpoint"]["status"] == "UPGRADE_REQUIRED"
    assert ops.upgrade_databases(**paths)["status"] == "READY"
    # A Workflow-only completed install may precede Checkpoint installation.
    # Empty downstream schemas do not prove cross-file staged facts existed.
    sql(paths["checkpoint"], "DROP TABLE staged_graph_checkpoints")
    assert ops.inspect_databases(**paths)["checkpoint"]["status"] == "UPGRADE_REQUIRED"
    assert ops.upgrade_databases(**paths)["status"] == "READY"


def test_staging_without_external_body_remains_a_legal_saga_cut(ready_handoff):
    rt, _, _, _, _, handoffs, _, _, handoff_id = ready_handoff
    dbs = database_paths(ready_handoff)
    # Exact typed intent produced before the external stage COMMIT. The formal
    # graph, completed prefix and receipts are unchanged; no Permit exists.
    staging = handoffs.get_handoff(handoff_id).model_copy(update={"status": "STAGING"})
    sql(dbs["workflow"], "UPDATE graph_handoffs SET status=?,payload=?,checksum=? WHERE handoff_id=?",
        (staging.status, staging.model_dump_json(by_alias=True), stable_checksum(staging), handoff_id))
    sql(dbs["checkpoint"], "DELETE FROM staged_graph_checkpoints WHERE handoff_id=?", (handoff_id,))
    before = contents(dbs)
    assert {v["status"] for v in ops.inspect_databases(**dbs).values()} == {"READY"}
    assert ops.upgrade_databases(**dbs)["status"] == "READY"
    assert contents(dbs) == before
