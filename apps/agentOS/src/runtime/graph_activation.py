"""Server-owned activation of an inactive materialization on its source Run.

Two explicit durable stages:

- ``prepare`` re-verifies the whole materialization/acceptance/safe-cut chain
  and persists one ``ACTIVATION_PREPARED`` journal row. It never touches the
  Run, so no scheduler can mistake preparation for activation.
- ``commit`` re-verifies everything again and, in a single Workflow
  ``BEGIN IMMEDIATE`` transaction, promotes the journal row to
  ``ACTIVATED_PAUSED``, upserts the formal ``graph_activation_heads`` version
  head, and switches the source Run's blueprint/package/plan projection to the
  candidate version while preserving the completed execution prefix.

``ACTIVATED_PAUSED`` is deliberately not an execution permit: the projection
carries ``executionPermit: None`` and every scheduling entry point keeps
refusing the Run until S03-02B issues a separately verified permit.
"""
import sqlite3
from pydantic import TypeAdapter
from contracts import stable_checksum
from contracts.compiled_acg import load_compiled_acg_package
from contracts.graph_activation import (
    GraphActivationReceipt,
    GraphActivationRecord,
    activation_projection,
)
from contracts.graph_revision import Ref
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from contracts.workflow import RuntimeRunRecord, WorkflowStatus, utc_now
from contracts.execution import WorkflowProgressPhase
from runtime.graph_revision import GraphRevisionError
from runtime.semantic_revision import SemanticRevisionService
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.stores.planning_commit_store import content_fingerprint
from support.run_execution_fence import acquire_run_fence, RunFenceBusy


def rejected(code, reason):
    return GraphActivationReceipt(status="REJECTED", code=code, reason=reason)


def _run_from_ledger(store, run_id):
    with store.connection() as conn:
        row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "activation source Run unavailable")
    return RuntimeRunRecord.model_validate_json(row[0])


class GraphActivationAuthority:
    def __init__(self, runtime, store):
        materialization = runtime.graph_materialization_authority
        if materialization is None or store.db_path != materialization.store.db_path:
            raise ValueError("activation requires the attached materialization journal")
        if runtime.planning_commit_authority is None or store.db_path != runtime.planning_commit_authority.store.db_path:
            raise ValueError("activation requires the same authoritative Workflow ledger")
        if store.db_path != runtime.workflow_store.db_path.resolve():
            raise ValueError("activation journal must share the Workflow database")
        self.runtime, self.store = runtime, store

    def _verify(self, materialization, *, expected=None, principal=None):
        """Re-run the complete materialization/acceptance/safe-cut verification."""
        runtime, store = self.runtime, self.store
        if (runtime.graph_activation_authority is not self
                or runtime.graph_materialization_authority is None):
            raise GraphRevisionError(Code.AUTHORITY_DENIED, "activation authority unavailable")
        # Cheap Run-side identity checks first: activation is defined against the
        # source version of this exact Run, so a drifted blueprint or package is
        # reported as STALE_GRAPH before the expensive acceptance-chain rerun.
        run = _run_from_ledger(store, materialization.source_run_id)
        with runtime._execution_slot_guard:
            if run.run_id in runtime._active_execution_slots:
                raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "execution slot occupies the activation cut")
        if run.mission_id != materialization.mission_id:
            raise GraphRevisionError(Code.STALE_GRAPH, "activation Run belongs to another Mission")
        blueprint = run.acg_blueprint or {}
        if (blueprint.get("graphId") != materialization.graph_id
                or blueprint.get("version") != materialization.source_graph_version):
            raise GraphRevisionError(Code.STALE_GRAPH, "Run blueprint is not the activation source version")
        persisted_package = run.execution_state.get("compiledACGPackage")
        if not isinstance(persisted_package, dict):
            raise GraphRevisionError(Code.STALE_GRAPH, "Run has no compiled source package")
        source_package = load_compiled_acg_package(persisted_package)
        if source_package.blueprint_version != materialization.source_graph_version:
            raise GraphRevisionError(Code.STALE_GRAPH, "Run package is not the activation source version")
        receipts = runtime.execution_value_store.list_node_commits(run_id=run.run_id)
        graph, caller = runtime.graph_materialization_authority._validate(
            materialization.source_commit_id, expected=expected, principal=principal)
        if any(receipt.get("stage") != "committed" for receipt in receipts):
            raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "unsettled work receipts cannot prove an activation cut")
        proposal = graph.proposal_payload
        if (materialization.commitment_fingerprint != content_fingerprint(graph)
                or materialization.proof_fingerprint != content_fingerprint(proposal.safe_cut)
                or materialization.sources != graph.sources
                or proposal.candidate_graph.version != materialization.candidate_graph_version
                or proposal.candidate_graph.graph_id != materialization.graph_id
                or materialization.package.blueprint_hash != stable_checksum(
                    proposal.candidate_graph.model_dump(mode="json", by_alias=True))):
            raise GraphRevisionError(Code.INVALID_PROPOSAL,
                                     "materialized package differs from the accepted candidate graph")
        SemanticRevisionService._validate_bindings(proposal.next_plan, proposal.candidate_graph,
                                                   proposal.next_bindings)
        return graph, run, caller

    def _replayable(self, key, materialization):
        """Return the already-prepared row when this key replays it exactly."""
        prepared = self.store.activation_by_key(key)
        if prepared is None:
            return None
        if (prepared.materialization_id != materialization.materialization_id
                or prepared.commitment_fingerprint != materialization.commitment_fingerprint
                or prepared.proof_fingerprint != materialization.proof_fingerprint
                or prepared.package_checksum != materialization.package_checksum):
            raise GraphRevisionError(Code.DUPLICATE_CONFLICT, "key binds another activation")
        return prepared

    def _competition(self, key, materialization):
        """Idempotency and head competition checks; caller holds the Run lock."""
        prepared = self._replayable(key, materialization)
        if prepared is not None:
            return prepared
        if self.store.activation_for(materialization.materialization_id) is not None:
            raise GraphRevisionError(Code.DUPLICATE_CONFLICT,
                                     "materialization already prepared; replay its original key")
        head = self.store.head(materialization.source_run_id)
        if head is not None:
            raise GraphRevisionError(Code.STALE_GRAPH, "Run already has a formal activated graph head")
        return None

    def prepare(self, materialization_id, *, idempotency_key):
        try:
            materialization_id = TypeAdapter(Ref).validate_python(materialization_id)
            key = TypeAdapter(Ref).validate_python(idempotency_key)
            materialization = self.store.get_materialization(materialization_id)
            if materialization is None:
                return rejected(Code.INVALID_PROPOSAL, "durable inactive materialization required")
            with self.runtime.run_lock_manager.lock_for(materialization.source_run_id), acquire_run_fence(
                    self.store.db_path, materialization.source_run_id):
                graph, _, principal = self._verify(materialization)
                prepared = self._competition(key, materialization)
                if prepared is not None:
                    return GraphActivationReceipt(status="IDEMPOTENT_REPLAY",
                                                  activationId=prepared.activation_id,
                                                  activeGraphVersion=prepared.candidate_graph_version)
                record = GraphActivationRecord(
                    activationId="gact_" + stable_checksum({
                        "materialization": materialization.materialization_id,
                        "commit": materialization.source_commit_id,
                        "package": materialization.package_checksum,
                        "policy": "activation-dag-v1"})[:40],
                    idempotencyKey=key, materializationId=materialization.materialization_id,
                    sourceCommitId=materialization.source_commit_id,
                    missionId=materialization.mission_id, runId=materialization.source_run_id,
                    graphId=materialization.graph_id,
                    sourceGraphVersion=materialization.source_graph_version,
                    candidateGraphVersion=materialization.candidate_graph_version,
                    packageChecksum=materialization.package_checksum,
                    commitmentFingerprint=materialization.commitment_fingerprint,
                    proofFingerprint=materialization.proof_fingerprint,
                    status="ACTIVATION_PREPARED")
                with self.store._transaction():
                    self.store._check_schema(self.store._local.connection)
                    self._verify(materialization, expected=graph, principal=principal)
                    self._competition(key, materialization)
                    self.store._append_activation(record)
            return GraphActivationReceipt(status="ACTIVATION_PREPARED", activationId=record.activation_id,
                                           activeGraphVersion=record.candidate_graph_version)
        except GraphRevisionError as exc:
            return rejected(exc.code, exc.reason)
        except RunFenceBusy:
            return rejected(Code.CONTROL_BARRIER_BLOCKED, "execution or activation occupies the cut")
        except (ValueError, KeyError, TypeError):
            return rejected(Code.INVALID_PROPOSAL, "invalid activation evidence")
        except (sqlite3.Error, RuntimeError):
            return rejected(Code.STORAGE_UNAVAILABLE, "activation storage unavailable; reconcile original key")

    def commit(self, materialization_id, *, idempotency_key):
        try:
            materialization_id = TypeAdapter(Ref).validate_python(materialization_id)
            key = TypeAdapter(Ref).validate_python(idempotency_key)
            materialization = self.store.get_materialization(materialization_id)
            if materialization is None:
                return rejected(Code.INVALID_PROPOSAL, "durable inactive materialization required")
            prepared = self.store.activation_for(materialization.materialization_id)
            if prepared is None:
                return rejected(Code.INVALID_PROPOSAL, "durable activation preparation required first")
            if prepared.idempotency_key != key:
                return rejected(Code.DUPLICATE_CONFLICT, "activation key does not match the prepared fact")
            with self.runtime.run_lock_manager.lock_for(materialization.source_run_id), acquire_run_fence(
                    self.store.db_path, materialization.source_run_id):
                # Reconciliation first: once this activation owns the formal head,
                # the Run projection legitimately holds the candidate version, so
                # full source verification would (correctly) refuse. Replaying the
                # committed fact must still return its identity.
                replay = self._head_state(prepared)
                if replay is not None:
                    return replay
                graph, run, principal = self._verify(materialization)
                activated_run = self._activated_run(run, materialization, graph, prepared)
                with self.store._transaction():
                    conn = self.store._local.connection
                    self.store._check_schema(conn)
                    current = self.store.activation_for(materialization.materialization_id)
                    if current != prepared:
                        raise GraphRevisionError(Code.DUPLICATE_CONFLICT, "prepared activation fact changed")
                    replay = self._head_state(prepared)
                    if replay is not None:
                        return replay
                    self._verify(materialization, expected=graph, principal=principal)
                    self.store._activate_head(prepared)
                    SQLiteWorkflowStore._upsert_run(conn, activated_run)
            return GraphActivationReceipt(status="ACTIVATED_PAUSED", activationId=prepared.activation_id,
                                           activeGraphVersion=prepared.candidate_graph_version)
        except GraphRevisionError as exc:
            return rejected(exc.code, exc.reason)
        except RunFenceBusy:
            return rejected(Code.CONTROL_BARRIER_BLOCKED, "execution or activation occupies the cut")
        except (ValueError, KeyError, TypeError):
            return rejected(Code.INVALID_PROPOSAL, "invalid activation evidence")
        except (sqlite3.Error, RuntimeError):
            return rejected(Code.STORAGE_UNAVAILABLE, "activation storage unavailable; reconcile original key")

    def _head_state(self, prepared):
        """Classify the current formal head for this prepared activation.

        ``None`` means the head is absent or continues from this activation's
        source version, so the promotion may proceed. A receipt is returned for
        an already-committed activation; anything else is a hard reject.
        """
        # Replay is a read of a committed fact, not permission to execute. Keep
        # head, checksummed journals and Run in the same SQLite snapshot.
        from support.stores.graph_activation_store import validate_activation_run
        with self.store.connection() as conn:
            own_snapshot = not conn.in_transaction
            if own_snapshot:
                conn.execute("BEGIN")
            try:
                row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (prepared.run_id,)).fetchone()
                if row is None:
                    raise ValueError("activation head source Run unavailable")
                head = validate_activation_run(conn, RuntimeRunRecord.model_validate_json(row["payload"]))
            finally:
                if own_snapshot:
                    conn.rollback()
        if head is None:
            return None
        if head.activation_id == prepared.activation_id:
            return GraphActivationReceipt(status="IDEMPOTENT_REPLAY",
                                          activationId=prepared.activation_id,
                                          activeGraphVersion=prepared.candidate_graph_version)
        if head.active_graph_version != prepared.source_graph_version:
            raise GraphRevisionError(Code.STALE_GRAPH,
                                     "formal graph head does not continue from this source")
        return None

    def _activated_run(self, run, materialization, graph, prepared):
        """Build the in-place v2 projection outside the final transaction.

        The completed execution prefix (steps, receipt references, completed
        IDs and every ACG evidence channel) is carried over untouched; the
        superseded checkpoint reference is detached but never deleted.
        """
        proposal = graph.proposal_payload
        blueprint = proposal.candidate_graph
        activated = run.model_copy(deep=True)
        activated.acg_blueprint = blueprint.model_dump(by_alias=True, mode="json")
        activated.execution_state.update({
            "graphId": blueprint.graph_id,
            "graphVersion": blueprint.version,
            "sourceBlueprintVersion": blueprint.version,
            "taskPlan": proposal.next_plan.model_dump(by_alias=True, mode="json"),
            "taskPlanVersion": proposal.next_plan.plan_version,
            "taskBindings": [item.model_dump(by_alias=True, mode="json") for item in proposal.next_bindings],
            "compiledACGPackage": materialization.package.model_dump(by_alias=True, mode="json"),
            "compiledPackageId": materialization.package.package_id,
            "compiledPackageChecksum": materialization.package.checksum,
            "compiledPackageVersion": materialization.package.package_version,
            "compiledPackageBlueprintHash": materialization.package.blueprint_hash,
            "graphDiff": proposal.graph_patch.model_dump(by_alias=True, mode="json"),
            "checkpointId": None,
            "graphActivation": activation_projection(
                prepared, superseded_checkpoint_id=activated.execution_state.get("checkpointId")),
        })
        activated.active_step_ids = []
        if activated.status == WorkflowStatus.WAITING_REVIEW:
            # The acknowledged v1 planner barrier has been superseded together
            # with its checkpoint. Retain its history, but do not represent the
            # v2 pause as a resumable v1 review. The durable Head still denies
            # all execution until a separately verified permit handoff exists.
            activated.status = self.runtime.state_machine.transition(activated.status, WorkflowStatus.RETRYING)
            activated.lifecycle_phase = WorkflowProgressPhase.RECOVERY
            activated.lifecycle_message = "Graph activated; awaiting verified execution handoff."
        activated.runtime_revision += 1
        activated.updated_at = utc_now()
        self.runtime._sync_run_steps_to_acg(activated, blueprint)
        # Candidate package additions (for example a newly accepted Step D)
        # must carry their compiled eligibility requirements before the
        # separate Permit allows the Scheduler to inspect the graph. This is
        # a pure projection: it neither reserves nor binds a Runtime.
        from runtime.binding import execution_requirements_for
        workflow = self.runtime._workflow_for_run(run)
        activated.execution_state["bindingRequirements"] = execution_requirements_for(
            materialization.package.binding_manifest,
            (step.step_id for step in activated.steps),
            domain=run.domain or workflow.domain,
        )
        return activated


__all__ = ["GraphActivationAuthority", "rejected"]
