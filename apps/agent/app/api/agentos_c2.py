"""HTTP adapters for the existing Initial C2 authorities; no execution dispatch."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.security.internal_auth import current_semantic_principal
from contracts.workflow import MissionRecordState, RunRecordState, RuntimeRunRecord
from contracts.planning_commit import PlanningCommitRecord
from contracts.graph_materialization import GraphMaterializationRecord
from contracts.initial_planning import InitialPlanningSourceProvenance
from contracts import stable_checksum
from support.stores.graph_activation_store import SQLiteGraphActivationStore, validate_activation_run


class MaterializeInitialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    operation_id: str = Field(alias="operationId", min_length=1, max_length=200)
    commit_id: str = Field(alias="commitId", min_length=1, max_length=300)
    expected_commitment_revision: int = Field(alias="expectedCommitmentRevision", strict=True, ge=1)


class ActivateInitialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    operation_id: str = Field(alias="operationId", min_length=1, max_length=200)
    materialization_id: str = Field(alias="materializationId", min_length=1, max_length=300)
    expected_graph_id: str = Field(alias="expectedGraphId", min_length=1, max_length=300)
    expected_graph_version: int = Field(alias="expectedGraphVersion", strict=True, ge=1)


@contextmanager
def control_errors():
    try:
        yield
    except PermissionError as exc:
        raise HTTPException(403, "semantic access denied") from exc
    except KeyError as exc:
        raise HTTPException(404, "C2 source not found") from exc
    except (RuntimeError, sqlite3.Error, ValueError, TypeError) as exc:
        # Never return compiler sources, signatures, storage paths or audit bodies.
        raise HTTPException(503, "C2 evidence unavailable; retry the same operation") from exc


def require_c2(runtime, mission_id, run_id, *, write):
    if any(getattr(runtime, name, None) is None for name in (
        "planning_commit_authority", "graph_materialization_authority", "graph_activation_authority",
    )):
        raise HTTPException(409, "C2 control is not enabled")
    principal = current_semantic_principal()
    if principal is None or runtime.semantic_principal_provider() != principal:
        raise HTTPException(403, "trusted semantic principal is required")
    service = runtime.mission_semantic_service
    service.require_write_access(principal, mission_id) if write else service.require_read_access(principal, mission_id)
    mission = runtime.workflow_store.get_mission(mission_id)
    run = runtime.workflow_store.get_run(run_id)
    if mission.record_state != MissionRecordState.ACTIVE or run.record_state != RunRecordState.ACTIVE:
        raise HTTPException(404, "C2 source not found")
    if run.mission_id != mission_id or not run.execution_state.get("planningCommitRequired"):
        raise HTTPException(409, "Run is not a C2 source of this Mission")
    return run


def initial_commit(runtime, run, commit_id):
    record = runtime.planning_commit_authority.get_commit(commit_id)
    origin = getattr(record, "source_provenance", None)
    if (record is None or record.proposal_type != "initial_plan" or origin is None
            or record.mission_id != run.mission_id or origin.source_run_id != run.run_id):
        raise HTTPException(409, "initial Commit does not belong to this Mission/Run")
    return record


def operation_key(action, run, operation_id):
    principal = current_semantic_principal()
    return "http-c2:" + hashlib.sha256(json.dumps([
        principal.tenant_id, principal.actor_id, action, run.mission_id, run.run_id, operation_id,
    ], separators=(",", ":")).encode()).hexdigest()


def receipt_response(receipt, operation_id):
    if receipt.status == "REJECTED":
        code = receipt.code.value
        status = 403 if code == "AUTHORITY_DENIED" else 503 if code == "STORAGE_UNAVAILABLE" else 409
        raise HTTPException(status, {"status": "REJECTED", "code": code, "operationId": operation_id})
    # Explicit public allowlist; the durable record is never serialized here.
    body = receipt.model_dump(by_alias=True, mode="json", exclude_none=True)
    return {"operationId": operation_id, **{k: v for k, v in body.items() if k in {
        "status", "materializationId", "activationId", "activeGraphVersion",
    }}}


def project_initial_control(runtime, run):
    """Read existing facts in one snapshot; preserve the legacy lifecycle status."""
    with control_errors():
        # load_run already checks owner/deletion. A switch disabling future C2
        # commands must not hide a previously persisted pause or grant execution.
        principal = current_semantic_principal()
        if principal is None:
            raise HTTPException(403, "trusted semantic principal is required")
        if runtime.mission_semantic_service is not None:
            runtime.mission_semantic_service.require_read_access(principal, run.mission_id)
        with runtime.workflow_store._connect() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            try:
                row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run.run_id,)).fetchone()
                current = RuntimeRunRecord.model_validate_json(row[0])
                head = validate_activation_run(conn, current)
                row = conn.execute("SELECT payload FROM planning_commit_records WHERE idempotency_key=?",
                                   ("initial-planning:" + run.run_id,)).fetchone()
                commit = PlanningCommitRecord.model_validate_json(row[0]) if row else None
                if commit and (commit.mission_id != current.mission_id
                        or not isinstance(commit.source_provenance, InitialPlanningSourceProvenance)
                        or commit.source_provenance.source_run_id != current.run_id):
                    raise ValueError("initial Commit source mismatch")
                row = conn.execute("SELECT * FROM graph_materializations WHERE source_commit_id=?",
                                   (commit.commit_id,)).fetchone() if commit else None
                mat = GraphMaterializationRecord.model_validate_json(row["payload"]) if row else None
                if mat and (stable_checksum(mat) != row["checksum"] or mat.source_commit_id != commit.commit_id
                            or mat.source_run_id != run.run_id or mat.mission_id != run.mission_id):
                    raise ValueError("materialization evidence mismatch")
                row = conn.execute("SELECT * FROM graph_activations WHERE materialization_id=?",
                                   (mat.materialization_id,)).fetchone() if mat else None
                prepared = SQLiteGraphActivationStore._decode_activation(row) if row else None
                result = {
                    "status": "ACTIVATED_PAUSED" if head else "ACTIVATION_PREPARED" if prepared else
                              "MATERIALIZED_INACTIVE" if mat else "PLANNING_ACCEPTED" if commit else "AWAITING_PLANNING",
                    "executionAuthorized": False,
                    "commitId": commit.commit_id if commit else None,
                    "commitmentRevision": commit.commitment_revision if commit else None,
                    "materializationId": mat.materialization_id if mat else None,
                    "activationId": head.activation_id if head else prepared.activation_id if prepared else None,
                    "graphId": head.graph_id if head else mat.graph_id if mat else None,
                    "graphVersion": head.active_graph_version if head else mat.candidate_graph_version if mat else None,
                }
                # A separately issued durable Permit must not be shown as paused.
                if (current.execution_state.get("graphActivation") or {}).get("executionPermit") is not None:
                    result["status"] = "ACTIVATED"
                    result["executionAuthorized"] = True
                return result
            finally:
                conn.rollback()


def create_c2_router(runtime):
    router = APIRouter()

    @router.post("/missions/{mission_id}/runs/{run_id}/graph/materializations")
    def materialize(mission_id: str, run_id: str, request: MaterializeInitialRequest):
        with control_errors():
            run = require_c2(runtime, mission_id, run_id, write=True)
            commit = initial_commit(runtime, run, request.commit_id)
            if commit.commitment_revision != request.expected_commitment_revision:
                raise HTTPException(409, "Commitment revision changed")
            receipt = runtime.materialize_initial_commit(commit.commit_id,
                idempotency_key=operation_key("materialize", run, request.operation_id))
            result = receipt_response(receipt, request.operation_id)
            mat = runtime.graph_materialization_authority.store.get_materialization(receipt.materialization_id)
            return {**result, "graphId": mat.graph_id, "graphVersion": mat.candidate_graph_version}

    @router.post("/missions/{mission_id}/runs/{run_id}/graph/activation")
    def activate(mission_id: str, run_id: str, request: ActivateInitialRequest):
        with control_errors():
            run = require_c2(runtime, mission_id, run_id, write=True)
            mat = runtime.graph_materialization_authority.store.get_materialization(request.materialization_id)
            if (mat is None or mat.source_kind != "initial_plan" or mat.mission_id != mission_id
                    or mat.source_run_id != run_id):
                raise HTTPException(409, "Materialization does not belong to this Mission/Run")
            initial_commit(runtime, run, mat.source_commit_id)
            if (mat.graph_id != request.expected_graph_id
                    or mat.candidate_graph_version != request.expected_graph_version):
                raise HTTPException(409, "Graph identity or version changed")
            key = operation_key("activate", run, request.operation_id)
            receipt_response(runtime.prepare_graph_activation(mat.materialization_id, idempotency_key=key), request.operation_id)
            return receipt_response(runtime.commit_graph_activation(mat.materialization_id, idempotency_key=key), request.operation_id)

    return router
