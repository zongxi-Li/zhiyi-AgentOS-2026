"""Issue the first durable execution permit for a verified graph handoff.

The service coordinates three durable stores as a retryable saga: Workflow owns
the PREPARING/ISSUED authority, Checkpoint owns the promoted immutable state,
and Identity owns the same-Run graph/semantic projection. Only the final
Workflow transaction changes the formal Run projection to executable.
"""

import hashlib
import json
import sqlite3
from types import SimpleNamespace

from pydantic import TypeAdapter

from contracts import stable_checksum
from contracts.execution_permit import (
    ExecutionPermitRecord,
    ExecutionPermitReceipt,
    execution_permit_projection,
)
from contracts.graph_revision import GraphRevisionProposal, Ref
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from contracts.workflow import RuntimeRunRecord, WorkflowStatus, utc_now
from components.recovery.checkpoint import CheckpointConflictError
from runtime.graph_revision import GraphProvider
from runtime.planning_commit import fingerprint
from support.run_execution_fence import acquire_run_fence, RunFenceBusy
from support.stores.graph_activation_store import validate_activation_run
from support.stores.planning_commit_store import content_fingerprint
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


def rejected(code, reason):
    return ExecutionPermitReceipt(status="REJECTED", code=str(getattr(code, "value", code)), reason=reason)


class ExecutionPermitError(ValueError):
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
        super().__init__(reason)


def _candidate_identity_fingerprint(run_id, mission_id, proposal):
    return fingerprint({
        "runId": run_id,
        "missionId": mission_id,
        "blueprint": proposal.candidate_graph.model_dump(mode="json", by_alias=True),
        "taskPlan": proposal.next_plan.model_dump(mode="json", by_alias=True),
        "taskBindings": [item.model_dump(mode="json", by_alias=True) for item in proposal.next_bindings],
    })


class ExecutionPermitAuthority:
    """Server-owned permit issuance; never accepts candidate execution data."""

    def __init__(self, runtime, store):
        if (runtime.graph_handoff_authority is None
                or store.db_path != runtime.workflow_store.db_path.resolve()
                or store.db_path != runtime.graph_handoff_authority.store.db_path
                or runtime.checkpoint_store.db_path.resolve() != runtime.graph_handoff_authority.staged_store.db_path):
            raise ValueError("execution permit requires the authoritative Workflow, handoff and checkpoint stores")
        self.runtime, self.store = runtime, store

    def issue(self, handoff_id, *, idempotency_key):
        try:
            handoff_id = TypeAdapter(Ref).validate_python(handoff_id)
            key = TypeAdapter(Ref).validate_python(idempotency_key)
            handoff = self.store.get_handoff(handoff_id)
            if handoff is None or handoff.status != "STATE_PREPARED":
                return rejected(Code.INVALID_PROPOSAL, "durable STATE_PREPARED handoff required")
            rt = self.runtime
            with rt.run_lock_manager.lock_for(handoff.run_id), acquire_run_fence(self.store.db_path, handoff.run_id):
                record = self.store.permit_by_key(key)
                if record is not None:
                    if record.handoff_id != handoff_id or record.handoff_fingerprint != content_fingerprint(handoff):
                        return rejected(Code.DUPLICATE_CONFLICT, "idempotency key binds another execution handoff")
                    if record.status == "ISSUED":
                        return ExecutionPermitReceipt(status="IDEMPOTENT_REPLAY", permitId=record.permit_id,
                                                      runId=record.run_id, graphVersion=record.graph_version)
                    if record.status == "REVOKED":
                        return rejected(Code.AUTHORITY_DENIED, "execution permit has been revoked")
                else:
                    existing_for_handoff = self.store.permit_for_handoff(handoff_id)
                    if existing_for_handoff is not None:
                        return rejected(Code.DUPLICATE_CONFLICT, "handoff is already bound to another permit key")
                    try:
                        candidate = rt.graph_handoff_authority._validated_candidate(
                            handoff.activation_id, handoff.idempotency_key)
                    except Exception as exc:
                        raise ExecutionPermitError(Code.INVALID_PROPOSAL, "prepared handoff sources are no longer valid") from exc
                    if candidate != handoff.model_copy(update={"status": "STAGING"}):
                        raise ExecutionPermitError(Code.INVALID_PROPOSAL, "handoff content differs from current verified sources")
                    record = self._new_record(handoff, candidate, key)
                    with self.store._transaction():
                        current_handoff = self.store.handoff_by_key(handoff.idempotency_key)
                        run = self._workflow_run(handoff.run_id)
                        if current_handoff != handoff or content_fingerprint(run) != record.source_run_fingerprint:
                            raise ExecutionPermitError(Code.STALE_GRAPH, "Run or handoff changed before permit preparation")
                        current_by_key = self.store.permit_by_key(key)
                        current_for_handoff = self.store.permit_for_handoff(handoff_id)
                        if current_by_key is not None or current_for_handoff is not None:
                            raise ExecutionPermitError(Code.DUPLICATE_CONFLICT, "another permit preparation already owns this handoff")
                        self.store._append_preparing(record)

                return self._reconcile(record)
        except ExecutionPermitError as exc:
            return rejected(exc.code, exc.reason)
        except RunFenceBusy:
            return rejected(Code.CONTROL_BARRIER_BLOCKED, "execution, activation or permit operation holds the Run fence")
        except (ValueError, KeyError, TypeError, AttributeError):
            return rejected(Code.INVALID_PROPOSAL, "invalid, stale or incomplete execution handoff")
        except (sqlite3.Error, RuntimeError):
            return rejected(Code.STORAGE_UNAVAILABLE, "permit storage unavailable; reconcile with the original key")

    def _new_record(self, handoff, candidate, key):
        rt = self.runtime
        run = self._workflow_run(handoff.run_id)
        # Activation IDs and handoff IDs are separate namespaces. The graph
        # commitment is reached through the activation's immutable source ref.
        activation = self.store.get_activation(handoff.activation_id)
        if activation is None or activation.status != "ACTIVATED_PAUSED":
            raise ExecutionPermitError(Code.STALE_GRAPH, "activated paused graph required")
        commitment = self.store.get(activation.source_commit_id)
        if commitment is None:
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "accepted Graph Revision required")
        if handoff.source_kind != activation.source_kind:
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "permit source kind differs from activation")
        if handoff.source_kind == "initial_plan":
            from runtime.initial_execution import initial_content
            _, _, content = initial_content(self.store, activation)
            proposal = SimpleNamespace(candidate_graph=content.blueprint, next_plan=content.plan, next_bindings=content.bindings)
        else:
            proposal = commitment.proposal_payload
            if not isinstance(proposal, GraphRevisionProposal):
                raise ExecutionPermitError(Code.INVALID_PROPOSAL, "accepted Graph Revision required")
        principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
        principal_fp = fingerprint(principal.model_dump(mode="json") if hasattr(principal, "model_dump") else principal)
        staged = rt.graph_handoff_authority.staged_store.get(candidate.candidate.checkpoint_id)
        if staged != candidate.candidate:
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "durable staged checkpoint differs from handoff")
        handoff_fingerprint = content_fingerprint(handoff)
        permit_id = "xpermit_" + stable_checksum({"handoff": handoff.handoff_id, "key": key,
                                                   "stage": candidate.candidate_fingerprint})[:40]
        generation = "agen_" + stable_checksum({"permit": permit_id, "run": run.run_id,
                                                  "graph": candidate.graph_version})[:32]
        promoted_id = "acgckpt_" + stable_checksum({"permit": permit_id,
                                                     "staged": candidate.candidate_fingerprint})[:24]
        return ExecutionPermitRecord(
            sourceKind=handoff.source_kind,
            permitId=permit_id, idempotencyKey=key, handoffId=handoff.handoff_id,
            activationId=handoff.activation_id, missionId=run.mission_id, runId=run.run_id,
            graphId=candidate.identity_link.candidate_graph.graph_id, graphVersion=candidate.graph_version,
            packageChecksum=candidate.candidate.package_checksum,
            stagedCheckpointId=candidate.candidate.checkpoint_id,
            stagedCheckpointFingerprint=content_fingerprint(staged),
            sourceCheckpointId=candidate.source_checkpoint_id,
            sourceCheckpointVersion=candidate.source_checkpoint_version,
            promotedCheckpointId=promoted_id,
            promotedCheckpointVersion=(candidate.source_checkpoint_version or 0) + 1,
            sourceRunFingerprint=content_fingerprint(run), handoffFingerprint=handoff_fingerprint,
            sourceIdentityFingerprint=candidate.identity_link.source_identity_fingerprint,
            candidateIdentityFingerprint=_candidate_identity_fingerprint(run.run_id, run.mission_id, proposal),
            principalFingerprint=principal_fp, attemptGeneration=generation, status="PREPARING")

    def _workflow_run(self, run_id):
        with self.store.connection() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ExecutionPermitError(Code.STALE_GRAPH, "source Run unavailable")
        return RuntimeRunRecord.model_validate_json(row[0])

    def _reconcile(self, record):
        rt = self.runtime
        handoff = self.store.get_handoff(record.handoff_id)
        if handoff is None or content_fingerprint(handoff) != record.handoff_fingerprint:
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "prepared handoff identity changed")
        # The original B1 verifier runs before the first external promotion. If
        # a previous process already promoted one store, the deterministic
        # per-store identities below validate that exact partial result.
        promoted_cp = self._promoted_checkpoint_payload(record, handoff)
        checkpoint_already_promoted = self._checkpoint_is_promoted(record, promoted_cp)
        identity_already_promoted = self._identity_matches_candidate(record, handoff)
        if not checkpoint_already_promoted and not identity_already_promoted:
            try:
                current = rt.graph_handoff_authority._validated_candidate(handoff.activation_id, handoff.idempotency_key)
            except Exception as exc:
                raise ExecutionPermitError(Code.INVALID_PROPOSAL, "source evidence changed before external handoff promotion") from exc
            if current != handoff.model_copy(update={"status": "STAGING"}):
                raise ExecutionPermitError(Code.INVALID_PROPOSAL, "current handoff differs from verified preparation")
        self._assert_workflow_fence(record, handoff, require_unissued=True)
        if not checkpoint_already_promoted:
            try:
                rt.checkpoint_store.save_promoted(run_id=record.run_id, checkpoint_id=record.promoted_checkpoint_id,
                    state=promoted_cp, expected_source_version=record.source_checkpoint_version or 0)
            except CheckpointConflictError as exc:
                raise ExecutionPermitError(Code.STALE_GRAPH, "checkpoint source advanced during Permit promotion") from exc
        self._promote_identity(record, handoff)
        self._assert_external_promotions(record, handoff, promoted_cp)
        self._assert_workflow_fence(record, handoff, require_unissued=True)
        with self.store._transaction():
            current = self.store.get_permit(record.permit_id)
            if current == record:
                run = self._workflow_run(record.run_id)
                self._assert_workflow_fence(record, handoff, require_unissued=True, conn=self.store._local.connection)
                self._assert_external_promotions(record, handoff, promoted_cp)
                issued = self.store._issue(record)
                permitted = run.model_copy(deep=True)
                projection = dict(permitted.execution_state["graphActivation"])
                projection["executionPermit"] = execution_permit_projection(issued)
                permitted.execution_state.update({
                    "graphActivation": projection,
                    "executionPermitId": issued.permit_id,
                    "executionGeneration": issued.attempt_generation,
                    "checkpointId": issued.promoted_checkpoint_id,
                })
                permitted.runtime_revision += 1
                permitted.updated_at = utc_now()
                conn = self.store._local.connection
                conn.row_factory = sqlite3.Row
                if not SQLiteWorkflowStore._upsert_run(conn, permitted):
                    raise ExecutionPermitError(Code.STALE_GRAPH, "Run became terminal before permit issuance")
            elif current is not None and current.status == "ISSUED":
                return ExecutionPermitReceipt(status="IDEMPOTENT_REPLAY", permitId=current.permit_id,
                                              runId=current.run_id, graphVersion=current.graph_version)
            else:
                raise ExecutionPermitError(Code.DUPLICATE_CONFLICT, "permit preparation changed during reconciliation")
        return ExecutionPermitReceipt(status="ISSUED", permitId=issued.permit_id, runId=issued.run_id,
                                      graphVersion=issued.graph_version)

    def _promoted_checkpoint_payload(self, record, handoff):
        staged = self.runtime.graph_handoff_authority.staged_store.get(record.staged_checkpoint_id)
        if staged is None or content_fingerprint(staged) != record.staged_checkpoint_fingerprint:
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "staged checkpoint content is missing or corrupt")
        if staged != handoff.candidate or staged.package_checksum != record.package_checksum:
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "staged checkpoint no longer matches accepted package")
        payload = dict(staged.state)
        payload["checkpointId"] = record.promoted_checkpoint_id
        payload["executionPermitId"] = record.permit_id
        payload["executionGeneration"] = record.attempt_generation
        if payload.get("graphVersion") != record.graph_version or payload.get("runId") != record.run_id:
            raise ExecutionPermitError(Code.STALE_GRAPH, "staged checkpoint identity mismatch")
        return payload

    def _checkpoint_is_promoted(self, record, payload):
        store = self.runtime.checkpoint_store
        try:
            saved = store.load(run_id=record.run_id, checkpoint_id=record.promoted_checkpoint_id)
            version = store.version(run_id=record.run_id, checkpoint_id=record.promoted_checkpoint_id)
            latest = store.latest_version(run_id=record.run_id)
        except KeyError:
            return False
        if (saved != payload or version != record.promoted_checkpoint_version or latest != version):
            raise ExecutionPermitError(Code.STALE_GRAPH, "promoted checkpoint is stale or differs from the permit")
        return True

    def _promote_identity(self, record, handoff):
        if self._identity_matches_candidate(record, handoff):
            return
        if self.runtime.identity_lifecycle is None:
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "Identity projection authority unavailable")
        proposal = self._proposal_for(record)
        repos = self.runtime.identity_lifecycle.repositories
        if record.source_kind == "initial_plan":
            run = self._workflow_run(record.run_id)
            mission = self.runtime.workflow_store.get_mission(record.mission_id)
            # Existing Lifecycle operation writes Plan/Blueprint/Run atomically
            # within Identity. It creates no Attempt or execution receipt.
            self.runtime.identity_lifecycle.on_run_prepared(
                mission, run, proposal.candidate_graph, proposal.next_plan, proposal.next_bindings)
            if not self._identity_matches_candidate(record, handoff):
                raise ExecutionPermitError(Code.INVALID_PROPOSAL, "Initial Identity registration did not match accepted content")
            return
        identity_run = repos.runs.get(record.run_id)
        if identity_run is None or identity_run.blueprint_id != handoff.identity_link.source_blueprint_id:
            raise ExecutionPermitError(Code.STALE_GRAPH, "Identity Run is not at the frozen source version")
        if identity_run.graph_version != int(handoff.identity_link.source_graph.version):
            raise ExecutionPermitError(Code.STALE_GRAPH, "Identity Run version differs from the frozen source")
        self.runtime.identity_lifecycle.on_execution_permit_blueprint_promoted(
            SimpleNamespace(run_id=record.run_id, mission_id=record.mission_id),
            proposal.candidate_graph, proposal.next_plan, proposal.next_bindings, record.permit_id)
        if not self._identity_matches_candidate(record, handoff):
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "Identity projection did not match the accepted candidate")

    def _proposal_for(self, record):
        activation = self.store.get_activation(record.activation_id)
        graph = self.store.get(activation.source_commit_id) if activation is not None else None
        proposal = getattr(graph, "proposal_payload", None)
        if record.source_kind == "initial_plan":
            from runtime.initial_execution import initial_content
            _, _, content = initial_content(self.store, activation)
            return SimpleNamespace(candidate_graph=content.blueprint, next_plan=content.plan, next_bindings=content.bindings,
                                   mission_revision=graph.source_revision)
        if not isinstance(proposal, GraphRevisionProposal):
            raise ExecutionPermitError(Code.INVALID_PROPOSAL, "accepted Graph Revision is unavailable")
        return proposal

    def _identity_matches_candidate(self, record, handoff):
        rt = self.runtime
        lifecycle = rt.identity_lifecycle
        if lifecycle is None:
            return False
        repos = lifecycle.repositories
        identity_run = repos.runs.get(record.run_id)
        if identity_run is None or identity_run.mission_id != record.mission_id:
            return False
        blueprint = repos.blueprints.get(identity_run.blueprint_id)
        if record.source_kind == "initial_plan":
            # Identity Blueprint versions are Mission-scoped allocations, while
            # the Activation Head versions this Run's graph. On a later Run of
            # the same Mission those counters need not both be 1. Bind BOTH the
            # Identity allocation and the complete Runtime graph/package.
            if (blueprint is None or identity_run.graph_version != blueprint.version
                    or blueprint.mission_id != record.mission_id or blueprint.graph_id != record.graph_id
                    or blueprint.graph.get("version") != record.graph_version
                    or blueprint.graph.get("graphId") != record.graph_id
                    or identity_run.metadata.get("runtimeGraphId") != record.graph_id
                    or identity_run.metadata.get("compiledPackageChecksum") != record.package_checksum):
                return False
        elif identity_run.graph_version != record.graph_version:
            return False
        plan = repos.task_plans.latest(record.mission_id)
        proposal = self._proposal_for(record)
        if (blueprint is None or blueprint.graph != proposal.candidate_graph.model_dump(mode="json", by_alias=True)
                or plan != proposal.next_plan):
            return False
        try:
            from domain.identity_graph.resolver import IdentityResolver
            bindings = {item.plan_node_key: item.acg_node_id for item in proposal.next_bindings}
            if set(bindings) != {node.key for node in proposal.next_plan.nodes}:
                return False
            for node in proposal.next_plan.nodes:
                resolved = IdentityResolver(repos).resolve_semantic_task(blueprint_id=blueprint.blueprint_id,
                                                                         acg_node_id=bindings[node.key])
                with repos.storage.read() as conn:
                    row = conn.execute("SELECT task_id,payload_json FROM task_plan_nodes WHERE mission_id=? AND plan_version=? AND semantic_key=?",
                                       (record.mission_id, plan.plan_version, node.key)).fetchone()
                if (row is None or resolved.mission_id != record.mission_id or resolved.semantic_task_key != node.key
                        or resolved.task_id != row["task_id"]
                        or json.loads(row["payload_json"]) != node.model_dump(mode="json", by_alias=True)):
                    return False
        except (ValueError, KeyError, AttributeError, TypeError):
            return False
        return _candidate_identity_fingerprint(record.run_id, record.mission_id, proposal) == record.candidate_identity_fingerprint

    def _assert_workflow_fence(self, record, handoff, *, require_unissued, conn=None):
        rt = self.runtime
        if record.source_kind == "initial_plan" and rt.execution_permit_authority is not self:
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "Initial execution Permit authority detached")
        owns = conn is None
        if owns:
            context = self.store.connection()
            conn = context.__enter__()
        try:
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (record.run_id,)).fetchone()
            if row is None:
                raise ExecutionPermitError(Code.STALE_GRAPH, "source Run disappeared")
            run = RuntimeRunRecord.model_validate_json(row[0])
            if content_fingerprint(run) != record.source_run_fingerprint:
                raise ExecutionPermitError(Code.STALE_GRAPH, "Run changed after handoff permit preparation")
            if rt._run_cancellation_requested(run.run_id) or run.status in {
                WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED, WorkflowStatus.SUPERSEDED,
            }:
                raise ExecutionPermitError(Code.AUTHORITY_DENIED, "Run is cancelled or terminal")
            if run.execution_state.get("graphActivation", {}).get("executionPermit") is not None:
                raise ExecutionPermitError(Code.DUPLICATE_CONFLICT, "Run already carries an execution permit")
            head = validate_activation_run(conn, run)
            if head is None or head.activation_id != record.activation_id or head.active_graph_version != record.graph_version:
                raise ExecutionPermitError(Code.STALE_GRAPH, "formal Activation Head changed")
            current_handoff = self.store.handoff_by_key(handoff.idempotency_key)
            if current_handoff != handoff:
                raise ExecutionPermitError(Code.INVALID_PROPOSAL, "handoff journal changed")
            if require_unissued:
                current = self.store.get_permit(record.permit_id)
                if current != record or record.status != "PREPARING":
                    raise ExecutionPermitError(Code.DUPLICATE_CONFLICT, "permit is no longer the same PREPARING fact")
            mission = conn.execute("SELECT revision FROM mission_semantic_state WHERE mission_id=?", (record.mission_id,)).fetchone()
            if mission is None:
                raise ExecutionPermitError(Code.STALE_MISSION, "formal Mission state is missing")
            activation = self.store.get_activation(record.activation_id)
            if activation is None or activation.status != "ACTIVATED_PAUSED" or activation.run_id != record.run_id:
                raise ExecutionPermitError(Code.STALE_GRAPH, "activation journal changed")
            commitment = self.store.get(activation.source_commit_id)
            if commitment is None or self.store.latest(record.mission_id) != commitment:
                raise ExecutionPermitError(Code.STALE_MISSION, "accepted graph commitment is no longer current")
            proposal = commitment.proposal_payload
            mission_revision = commitment.source_revision if record.source_kind == "initial_plan" else getattr(proposal, "mission_revision", None)
            if ((record.source_kind == "graph_revision" and not isinstance(proposal, GraphRevisionProposal))
                    or mission[0] != mission_revision):
                raise ExecutionPermitError(Code.STALE_MISSION, "Mission revision differs from accepted graph source")
            principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
            principal_fp = fingerprint(principal.model_dump(mode="json") if hasattr(principal, "model_dump") else principal)
            if principal_fp != record.principal_fingerprint:
                raise ExecutionPermitError(Code.AUTHORITY_DENIED, "principal or authorization snapshot changed")
            if record.source_kind == "initial_plan":
                from runtime.initial_execution import assert_initial_sources, assert_initial_unexecuted
                assert_initial_sources(rt, self.store, run, commitment, allow_candidate_identity=True,
                                       principal_fingerprint=record.principal_fingerprint)
                if require_unissued:
                    assert_initial_unexecuted(rt, run)
            else:
                source = self.store.get(proposal.source_commit_id)
                provider = GraphProvider(rt.planning_commit_authority, record.run_id, proposal, source, principal)
                provider.store = self.store
                if source is None or not provider.authorize():
                    raise ExecutionPermitError(Code.AUTHORITY_DENIED, "current Mission execution authority denied")
            if run.execution_state.get("graphId") != record.graph_id or run.execution_state.get("graphVersion") != record.graph_version:
                raise ExecutionPermitError(Code.STALE_GRAPH, "Run projection differs from permitted graph")
        finally:
            if owns:
                context.__exit__(None, None, None)

    def _assert_dispatch_authority(self, record, *, check_run_fingerprint=False, check_checkpoint=True):
        rt = self.runtime
        if record.source_kind == "initial_plan" and rt.execution_permit_authority is not self:
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "Initial execution Permit authority detached")
        permit = self.store.get_permit(record.permit_id)
        if permit is None or permit.status != "ISSUED" or permit != record:
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "current execution permit is not issued")
        run = self._workflow_run(record.run_id)
        with self.store.connection() as conn:
            head = validate_activation_run(conn, run)
        if head is None or head.activation_id != record.activation_id:
            raise ExecutionPermitError(Code.STALE_GRAPH, "formal Activation Head changed before dispatch")
        activation_projection = (run.execution_state.get("graphActivation") or {})
        if (activation_projection.get("executionPermit") != execution_permit_projection(record)
                or run.execution_state.get("executionGeneration") != record.attempt_generation
                or run.execution_state.get("executionPermitId") != record.permit_id
                or run.execution_state.get("graphVersion") != record.graph_version):
            raise ExecutionPermitError(Code.STALE_GRAPH, "Run does not carry the current permit projection")
        if check_run_fingerprint and content_fingerprint(run) != record.source_run_fingerprint:
            raise ExecutionPermitError(Code.STALE_GRAPH, "Run changed before permit issuance")
        if rt._run_cancellation_requested(run.run_id) or run.status in {
            WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED, WorkflowStatus.SUPERSEDED,
        }:
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "Run is cancelled or terminal")
        principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
        principal_fp = fingerprint(principal.model_dump(mode="json") if hasattr(principal, "model_dump") else principal)
        if principal_fp != record.principal_fingerprint:
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "execution permission changed after permit issuance")
        activation = self.store.get_activation(record.activation_id)
        commitment = self.store.get(activation.source_commit_id) if activation else None
        source = self.store.get(commitment.parent_commit_id) if commitment and commitment.parent_commit_id else None
        if (activation is None or activation.status != "ACTIVATED_PAUSED"
                or commitment is None or self.store.latest(record.mission_id) != commitment):
            raise ExecutionPermitError(Code.STALE_GRAPH, "accepted graph or activation is no longer current")
        if record.source_kind == "initial_plan":
            from runtime.initial_execution import assert_initial_sources
            assert_initial_sources(rt, self.store, run, commitment, allow_candidate_identity=True,
                                   principal_fingerprint=record.principal_fingerprint)
        else:
            provider = GraphProvider(rt.planning_commit_authority, record.run_id, commitment.proposal_payload, source, principal)
            provider.store = self.store
            if source is None or not provider.authorize():
                raise ExecutionPermitError(Code.AUTHORITY_DENIED, "current Mission execution authority denied")
        with self.store.connection() as conn:
            row = conn.execute("SELECT revision FROM mission_semantic_state WHERE mission_id=?", (record.mission_id,)).fetchone()
        mission_revision = commitment.source_revision if record.source_kind == "initial_plan" else commitment.proposal_payload.mission_revision
        if row is None or row[0] != mission_revision:
            raise ExecutionPermitError(Code.STALE_MISSION, "Mission revision changed after permit issuance")
        handoff = self.store.get_handoff(record.handoff_id)
        if handoff is None or not self._identity_matches_candidate(record, handoff):
            raise ExecutionPermitError(Code.STALE_GRAPH, "permitted Identity projection changed")
        if check_checkpoint:
            self._assert_recovery_head(record, handoff, run)

    def _assert_recovery_head(self, record, handoff, run):
        """Require the acknowledged current head, allowing later native checkpoints.

        The immutable promoted body anchors the generation; subsequent native
        bodies use the existing content-derived checkpoint identity. An external
        write not yet acknowledged by Workflow is a recovery barrier, not a
        license to fall back to the permit's initial checkpoint.
        """
        store = self.runtime.checkpoint_store
        initial = store.load(run_id=record.run_id, checkpoint_id=record.promoted_checkpoint_id)
        if (initial != self._promoted_checkpoint_payload(record, handoff)
                or store.version(run_id=record.run_id, checkpoint_id=record.promoted_checkpoint_id)
                != record.promoted_checkpoint_version):
            raise ExecutionPermitError(Code.STALE_GRAPH, "promoted checkpoint is missing or corrupt")
        checkpoint_id, payload = store.load_latest(run_id=record.run_id)
        version = store.version(run_id=record.run_id, checkpoint_id=checkpoint_id)
        if (checkpoint_id != run.execution_state.get("checkpointId")
                or version < record.promoted_checkpoint_version
                or payload.get("checkpointId") != checkpoint_id
                or payload.get("runId") != record.run_id
                or payload.get("graphId") != record.graph_id
                or payload.get("graphVersion") != record.graph_version
                or payload.get("executionPermitId") != record.permit_id
                or payload.get("executionGeneration") != record.attempt_generation):
            raise ExecutionPermitError(Code.STALE_GRAPH, "current checkpoint head is not acknowledged by permitted Run")
        if checkpoint_id != record.promoted_checkpoint_id:
            body = dict(payload, checkpointId=None)
            encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected = "acgckpt_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
            if version <= record.promoted_checkpoint_version or expected != checkpoint_id:
                raise ExecutionPermitError(Code.STALE_GRAPH, "native checkpoint content or version is invalid")

    def assert_dispatchable(self, run):
        if "graphActivation" not in run.execution_state:
            return
        projection = (run.execution_state.get("graphActivation") or {}).get("executionPermit")
        if not isinstance(projection, dict):
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "activated Run is still paused without a durable permit")
        record = self.store.get_permit(projection.get("permitId"))
        if record is None or record.status != "ISSUED" or projection != execution_permit_projection(record):
            raise ExecutionPermitError(Code.AUTHORITY_DENIED, "execution permit is missing, stale or revoked")
        self._assert_dispatch_authority(record)

    def assert_invocation(self, run, state, step_id, attempt_id):
        """Bind the live Scheduler selection to durable Identity at invocation."""
        self.assert_dispatchable(run)
        current = self._workflow_run(run.run_id)
        if (state.run_id != current.run_id
                or state.graph_version != current.execution_state.get("graphVersion")
                or state.execution_permit_id != current.execution_state.get("executionPermitId")
                or state.execution_generation != current.execution_state.get("executionGeneration")):
            raise ExecutionPermitError(Code.STALE_GRAPH, "invocation belongs to a stale execution generation")
        binding = run.execution_state.get("executionBindings", {}).get(step_id)
        if (not isinstance(binding, dict)
                or binding != current.execution_state.get("executionBindings", {}).get(step_id)
                or binding.get("attemptId") != attempt_id or binding.get("runId") != run.run_id
                or binding.get("stepId") != step_id):
            raise ExecutionPermitError(Code.STALE_GRAPH, "Scheduler binding changed before invocation")
        repos = self.runtime.identity_lifecycle.repositories
        attempt = repos.attempts.get(attempt_id)
        identity_binding = repos.execution_bindings.get_for_attempt(attempt_id)
        from domain.identity_graph.resolver import IdentityResolver
        identity_run = repos.runs.get(run.run_id)
        task = IdentityResolver(repos).resolve_semantic_task(
            blueprint_id=identity_run.blueprint_id, acg_node_id=step_id)
        executions = repos.step_executions.list_for_attempt(attempt_id)
        if (attempt is None or attempt.run_id != run.run_id or attempt.task_id != task.task_id
                or identity_binding is None or identity_binding.acg_node_id != step_id
                or identity_binding.resource_id != binding.get("resourceId")
                or not any(item.run_id == run.run_id and item.task_id == task.task_id
                           and item.status.value == "running" for item in executions)):
            raise ExecutionPermitError(Code.STALE_GRAPH, "Identity Attempt or resource binding changed before invocation")

    def _assert_external_promotions(self, record, handoff, checkpoint_payload):
        if not self._checkpoint_is_promoted(record, checkpoint_payload):
            raise ExecutionPermitError(Code.STALE_GRAPH, "checkpoint promotion is incomplete")
        if not self._identity_matches_candidate(record, handoff):
            raise ExecutionPermitError(Code.STALE_GRAPH, "candidate Identity projection is incomplete")


__all__ = ["ExecutionPermitAuthority", "ExecutionPermitError", "rejected"]
