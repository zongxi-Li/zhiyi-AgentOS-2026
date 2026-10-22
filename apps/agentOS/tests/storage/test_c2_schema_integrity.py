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
from test_horizon import ready_boundary, runtime_boundary
from test_initial_planning_sources import initial_run


@pytest.fixture
def two_permits(initial_run):
    """Two real Initial authority chains, different Missions, one Workflow DB."""
    from contracts.mission_semantic import MissionSemanticRequest
    from test_initial_graph_materialization import setup_initial
    from test_graph_handoff import attach
    from support.stores.execution_permit_store import SQLiteExecutionPermitStore

    rt, workflow, agent, original, ledger = initial_run
    issued = []
    for index in range(2):
        if index == 0:
            run = original
        else:
            mission = rt.create_mission("Schema identity isolation", workflow_id=original.workflow_id)
            rt.mission_semantic_service.commit(rt.semantic_principal_provider(), MissionSemanticRequest(
                missionId=mission.mission_id, operationId="schema-second-mission", expectedMissionRevision=0,
                objective="Analyze input", constraints=[], sourceRefs=["input:brief"]))
            _, run = rt.prepare_run(mission.mission_id, workflow_id=original.workflow_id)
        context = setup_initial((rt, workflow, agent, run, ledger))
        record = context[4]
        mat = rt.materialize_initial_commit(record.commit_id, idempotency_key=f"mat:{run.run_id}")
        assert mat.status == "MATERIALIZED_INACTIVE", mat
        key = f"act:{run.run_id}"
        assert rt.prepare_graph_activation(mat.materialization_id, idempotency_key=key).status == "ACTIVATION_PREPARED"
        act = rt.commit_graph_activation(mat.materialization_id, idempotency_key=key)
        assert act.status == "ACTIVATED_PAUSED", act
        attach(rt, workflow)
        SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
        rt.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
        handoff = rt.prepare_graph_handoff(act.activation_id, idempotency_key=f"handoff:{run.run_id}")
        assert handoff.status == "STATE_PREPARED", handoff
        receipt = rt.issue_execution_permit(handoff.handoff_id, idempotency_key=f"permit:{run.run_id}")
        assert receipt.status == "ISSUED", receipt
        issued.append((workflow.get_run(run.run_id), rt.execution_permit_authority.store.get_permit(receipt.permit_id)))
    dbs = database_paths((rt, workflow))
    assert issued[0][1].graph_id != issued[1][1].graph_id
    assert {v["status"] for v in ops.inspect_databases(**dbs).values()} == {"READY"}
    return rt, workflow, dbs, issued


@pytest.mark.parametrize("damage", ["foreign_projection", "permit_mission", "permit_graph",
                                    "projection_version", "projection_activation", "projection_handoff"])
def test_run_permit_semantic_identity_is_checked_even_with_valid_checksums(two_permits, damage):
    from contracts.execution_permit import execution_permit_projection
    rt, workflow, dbs, issued = two_permits
    run, permit = issued[0]
    other_run, other_permit = issued[1]
    assert run.mission_id != other_run.mission_id and run.run_id != other_run.run_id
    if damage.startswith("permit_"):
        field, value = ("mission_id", other_permit.mission_id) if damage == "permit_mission" else ("graph_id", other_permit.graph_id)
        changed = permit.model_copy(update={field: value})
        sql(dbs["workflow"], "UPDATE graph_execution_permits SET payload=?,checksum=? WHERE permit_id=?",
            (changed.model_dump_json(by_alias=True), stable_checksum(changed), permit.permit_id))
        # The normal typed reader accepts the recomputed checksum. Rejection
        # must therefore come from semantic relationships, not corrupt bytes.
        assert rt.execution_permit_authority.store.get_permit(permit.permit_id) == changed
    else:
        projection = run.execution_state["graphActivation"]["executionPermit"]
        if damage == "foreign_projection":
            run.execution_state["graphActivation"]["executionPermit"] = execution_permit_projection(other_permit)
        else:
            field, value = {"projection_version": ("graphVersion", 2),
                            "projection_activation": ("activationId", other_permit.activation_id),
                            "projection_handoff": ("handoffId", other_permit.handoff_id)}[damage]
            projection[field] = value
        sql(dbs["workflow"], "UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run.run_id))
    before = contents(dbs)
    inspection = ops.inspect_databases(**dbs)
    assert inspection["workflow"]["status"] == "INVALID", inspection
    with pytest.raises(ops.SchemaUpgradeError, match="preflight rejected"):
        ops.upgrade_databases(**dbs)
    assert contents(dbs) == before


def test_two_valid_run_permits_remain_ready_without_mutation(two_permits):
    _, _, dbs, _ = two_permits
    before = contents(dbs)
    assert ops.upgrade_databases(**dbs)["status"] == "READY"
    assert contents(dbs) == before


def test_preflight_accepts_legal_native_checkpoint_advancement(two_permits):
    import asyncio
    rt, workflow, dbs, issued = two_permits
    run, permit = issued[0]
    completed = asyncio.run(rt.execute_prepared_run(run.run_id))
    assert completed.completed_step_ids == ["A"]
    assert completed.execution_state["checkpointId"] != permit.promoted_checkpoint_id
    assert rt.execution_value_store.list_node_commits(run_id=run.run_id)[0]["stage"] == "committed"
    assert workflow.get_run(run.run_id).completed_step_ids == ["A"]
    before = contents(dbs)
    assert {v["status"] for v in ops.inspect_databases(**dbs).values()} == {"READY"}
    assert contents(dbs) == before


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
