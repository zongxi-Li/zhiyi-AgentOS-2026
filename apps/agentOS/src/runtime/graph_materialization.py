"""Compile accepted graph facts outside the write lock; persist inactive only."""
import sqlite3
from pydantic import TypeAdapter
from contracts import stable_checksum
from contracts.graph_revision import GraphRevisionProposal, Ref
from contracts.graph_materialization import GraphMaterializationRecord, GraphMaterializationReceipt
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from components.executor.compiler import ACGGraphCompiler
from runtime.graph_revision import GraphProvider, GraphRevisionError, source_provenance, safe_cut
from runtime.semantic_revision import SemanticRevisionService
from support.stores.planning_commit_store import content_fingerprint


def rejected(code, reason):
    return GraphMaterializationReceipt(status="REJECTED", code=code, reason=reason)


class GraphMaterializationAuthority:
    def __init__(self, runtime, store):
        if runtime.planning_commit_authority is None or store.db_path != runtime.planning_commit_authority.store.db_path:
            raise ValueError("materialization requires the same authoritative Workflow ledger")
        if store.db_path != runtime.workflow_store.db_path.resolve():
            raise ValueError("materialization journal must share the Workflow database")
        self.runtime, self.store = runtime, store

    def _validate(self, commit_id, *, expected=None, principal=None):
        runtime, store = self.runtime, self.store
        if (runtime.graph_materialization_authority is not self or runtime.planning_commit_authority is None
                or runtime.planning_commit_authority.store.db_path != store.db_path):
            raise GraphRevisionError(Code.AUTHORITY_DENIED, "materialization authority unavailable")
        graph = store.get(commit_id)
        if graph is None or graph.proposal_type != "graph_revision" or not isinstance(graph.proposal_payload, GraphRevisionProposal):
            raise GraphRevisionError(Code.INVALID_PROPOSAL, "accepted graph revision required")
        if expected is not None and graph != expected:
            raise GraphRevisionError(Code.INVALID_PROPOSAL, "accepted content changed")
        proposal = graph.proposal_payload
        source = store.get(proposal.source_commit_id)
        if (source is None or source.proposal_type != "plan_revision" or graph.parent_commit_id != source.commit_id
                or graph.commitment_revision != source.commitment_revision + 1
                or graph.mission_id != source.mission_id or graph.source_revision != source.source_revision
                or proposal.source_proposal_fingerprint != source.proposal_fingerprint
                or proposal.mission_revision != graph.source_revision
                or proposal.source_provenance != source.source_provenance
                or graph.source_provenance != source.source_provenance
                or proposal.base_plan_version != source.sources.plan_version
                or graph.sources.plan_version != source.sources.plan_version
                or graph.sources.graph_version != source.sources.graph_version
                or graph.sources.observation_id != source.sources.observation_id
                or graph.sources.observation_fingerprint != source.sources.observation_fingerprint
                or proposal.graph_patch.base_graph_version != source.sources.graph_version
                or store.latest(graph.mission_id) != graph):
            raise GraphRevisionError(Code.STALE_COMMITMENT, "graph acceptance chain or head mismatch")
        # Verify the complete retained ancestry, bounded rather than truncating.
        current, seen = source, set()
        while current is not None:
            if current.commit_id in seen or len(seen) >= 256:
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "acceptance ancestry exceeds bounded policy")
            seen.add(current.commit_id)
            if current.parent_commit_id is None:
                if current.commitment_revision != 1:
                    raise GraphRevisionError(Code.INVALID_PROPOSAL, "missing acceptance ancestor")
                break
            parent = store.get(current.parent_commit_id)
            if parent is None or parent.mission_id != graph.mission_id or parent.commitment_revision + 1 != current.commitment_revision:
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "invalid acceptance ancestor")
            current = parent
        caller = runtime.semantic_principal_provider() if runtime.semantic_principal_provider else None
        if principal is not None and caller != principal:
            raise GraphRevisionError(Code.AUTHORITY_DENIED, "caller identity changed")
        provider = GraphProvider(runtime.planning_commit_authority, proposal.source_provenance.source_run_id,
                                 proposal, source, caller)
        # Route all Workflow reads through this transaction's connection.
        provider.store = store
        # Resolve identity hooks before checking the actual source and safe-cut
        # boundary. Such hooks can block while receipts/checkpoints or registry
        # inputs change; authorization alone cannot detect those changes.
        current_caller = runtime.semantic_principal_provider() if runtime.semantic_principal_provider else None
        if provider.authorize() is not True:
            raise GraphRevisionError(Code.AUTHORITY_DENIED, "materialization not authorized")
        if (provider.get_current_sources(graph.mission_id) != graph.sources
                or source_provenance(provider) != proposal.source_provenance):
            raise GraphRevisionError(Code.STALE_STRATEGY, "materialization sources changed")
        if safe_cut(provider, source, proposal.next_plan, proposal.next_bindings,
                    proposal.candidate_graph, proposal.graph_patch) != proposal.safe_cut:
            raise GraphRevisionError(Code.INVALID_PROPOSAL, "current safe-cut evidence differs")
        # No identity/source capture callbacks after the source fence.
        if (caller != current_caller or provider.authorize() is not True
                or runtime._run_cancellation_requested(provider.run_id)
                or runtime.graph_materialization_authority is not self
                or runtime.planning_commit_authority is not provider.authority):
            raise GraphRevisionError(Code.AUTHORITY_DENIED, "materialization authorization changed")
        return graph, caller

    def materialize(self, commit_id, *, idempotency_key):
        try:
            commit_id = TypeAdapter(Ref).validate_python(commit_id)
            key = TypeAdapter(Ref).validate_python(idempotency_key)
            graph = self.store.get(commit_id)
            if graph is None or not isinstance(graph.proposal_payload, GraphRevisionProposal):
                return rejected(Code.INVALID_PROPOSAL, "accepted graph revision required")
            run_id = graph.proposal_payload.source_provenance.source_run_id
            with self.runtime.run_lock_manager.lock_for(run_id):
                graph, principal = self._validate(commit_id, expected=graph)
                with self.store.connection() as conn:
                    self.store._check_schema(conn)
                old = self.store.materialization_by_key(key)
                if old is not None:
                    if (old.source_commit_id != commit_id or old.commitment_fingerprint != content_fingerprint(graph)
                            or old.proof_fingerprint != content_fingerprint(graph.proposal_payload.safe_cut)
                            or old.package.blueprint_hash != stable_checksum(graph.proposal_payload.candidate_graph.model_dump(mode="json", by_alias=True))):
                        return rejected(Code.DUPLICATE_CONFLICT, "key binds another materialization")
                    return GraphMaterializationReceipt(status="IDEMPOTENT_REPLAY", materializationId=old.materialization_id,
                                                       packageChecksum=old.package_checksum)
                if self.store.materialization_for(commit_id) is not None:
                    return rejected(Code.DUPLICATE_CONFLICT, "graph already materialized; replay original key")
            proposal = graph.proposal_payload
            # Both routines are pure. Never prepare a replacement Run or bind resources.
            SemanticRevisionService._validate_bindings(proposal.next_plan, proposal.candidate_graph, proposal.next_bindings)
            package = ACGGraphCompiler().compile_package(proposal.candidate_graph, run_id=run_id)
            record = GraphMaterializationRecord(materializationId="gmat_" + stable_checksum({
                "commit": commit_id, "package": package.checksum, "policy": "materialization-dag-v1"})[:40],
                idempotencyKey=key, sourceCommitId=commit_id, commitmentFingerprint=content_fingerprint(graph),
                missionId=graph.mission_id, sourceRunId=run_id, graphId=package.blueprint_id,
                sourceGraphVersion=graph.sources.graph_version, candidateGraphVersion=package.blueprint_version,
                sources=graph.sources, proofFingerprint=content_fingerprint(proposal.safe_cut),
                package=package, packageChecksum=package.checksum)
            if (package.blueprint_hash != stable_checksum(proposal.candidate_graph.model_dump(mode="json", by_alias=True))
                    or len(record.model_dump_json()) > 4_000_000):
                return rejected(Code.INVALID_PROPOSAL, "invalid or oversized compiled materialization")
            with self.runtime.run_lock_manager.lock_for(run_id), self.store._transaction():
                self.store._check_schema(self.store._local.connection)
                self._validate(commit_id, expected=graph, principal=principal)
                old = self.store.materialization_by_key(key)
                if old is not None:
                    if old != record:
                        return rejected(Code.DUPLICATE_CONFLICT, "key binds different immutable content")
                    return GraphMaterializationReceipt(status="IDEMPOTENT_REPLAY", materializationId=old.materialization_id,
                                                       packageChecksum=old.package_checksum)
                if self.store.materialization_for(commit_id) is not None:
                    return rejected(Code.DUPLICATE_CONFLICT, "graph already materialized; replay original key")
                self.store._append_materialization(record)
            return GraphMaterializationReceipt(status="MATERIALIZED_INACTIVE", materializationId=record.materialization_id,
                                               packageChecksum=record.package_checksum)
        except GraphRevisionError as exc:
            return rejected(exc.code, exc.reason)
        except (ValueError, KeyError, TypeError):
            return rejected(Code.INVALID_PROPOSAL, "invalid materialization evidence")
        except (sqlite3.Error, RuntimeError):
            return rejected(Code.STORAGE_UNAVAILABLE, "materialization storage unavailable; reconcile original key")
