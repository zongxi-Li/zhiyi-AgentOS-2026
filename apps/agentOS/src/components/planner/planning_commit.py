"""Provider-driven planning acceptance with pluggable record storage.

The provider owns trusted proposal lookup, permission checks, source snapshots and
semantic validation. Its guard must exclude changes to those inputs during acceptance.
No permissive provider is shipped: schema-valid input alone is never sufficient.
"""
from contextlib import contextmanager
import hashlib
import json
from threading import RLock
from typing import ContextManager, Mapping, Protocol
from uuid import uuid4

from pydantic import ValidationError
from contracts.initial_planning import InitialPlanningSourceProvenance

from contracts.planning_commit import (
    FrozenPlanningSources, PlanningCommitReceipt, PlanningCommitRecord,
    PlanningCommitRejection, PlanningCommitRejectionCode as Code, PlanningCommitRequest,
)


class CurrentPlanningStateProvider(Protocol):
    def planning_guard(self, mission_id: str) -> ContextManager[None]:
        """Exclude trusted state/proposal/auth changes until acceptance finishes.

        Providers must not acquire the commit store while holding this guard in
        another thread; lock order is commit store, then provider guard.
        """
        ...

    def get_current_sources(self, mission_id: str) -> FrozenPlanningSources:
        """Return one coherent snapshot, not three independently sampled versions."""
        ...

    def authorize(self, request: PlanningCommitRequest) -> bool:
        """Check trusted caller authority, including on idempotent receipt replay."""
        ...

    def validate_proposal(self, request: PlanningCommitRequest) -> PlanningCommitRejection | None:
        """Resolve server-owned candidate identity/type/fingerprint and scope.

        Must check source binding, dependency closure and control/review barriers
        against trusted validated proposal data. Return None only when proven.
        Reuse the existing topology authority; this service is not a compiler.
        """
        ...


class InMemoryPlanningCommitStore:
    """Process-local records and indexes; share this instance across services."""
    def __init__(self):
        self._lock = RLock()
        self._records: dict[str, PlanningCommitRecord] = {}
        self._by_key: dict[str, str] = {}
        self._latest: dict[str, str] = {}
        self.requires_durable_payload = False

    @contextmanager
    def _transaction(self):
        with self._lock:
            yield

    def get(self, commit_id: str) -> PlanningCommitRecord | None:
        with self._lock:
            record = self._records.get(commit_id)
            return PlanningCommitRecord.model_validate_json(record.model_dump_json(by_alias=True)) if record else None

    def get_by_idempotency_key(self, key: str) -> PlanningCommitRecord | None:
        with self._lock:
            return self.get(self._by_key.get(key, ""))

    def latest(self, mission_id: str) -> PlanningCommitRecord | None:
        with self._lock:
            return self.get(self._latest.get(mission_id, ""))

    def _append(self, key: str, record: PlanningCommitRecord) -> None:
        # Called only within the authority's transaction; no public arbitrary put.
        self._records[record.commit_id] = record
        self._by_key[key] = record.commit_id
        self._latest[record.mission_id] = record.commit_id

    def _rollback_append(self, key, record, parent):
        self._records.pop(record.commit_id, None)
        self._by_key.pop(key, None)
        if parent is None:
            self._latest.pop(record.mission_id, None)
        else:
            self._latest[record.mission_id] = parent.commit_id


class PlanningCommitService:
    def __init__(self, *, current_state_provider: CurrentPlanningStateProvider,
                 store: InMemoryPlanningCommitStore | None = None):
        self.provider = current_state_provider
        self.store = store if store is not None else InMemoryPlanningCommitStore()

    @staticmethod
    def _request(value) -> PlanningCommitRequest:
        # Revalidate even model instances: model_copy/model_construct bypass validators.
        if isinstance(value, PlanningCommitRequest):
            value = value.model_dump(mode="json", by_alias=True)
        return PlanningCommitRequest.model_validate(value)

    @staticmethod
    def _reject(code: Code, reason: str) -> PlanningCommitRejection:
        return PlanningCommitRejection(code=code, reason=reason)

    def _replay(self, request: PlanningCommitRequest, digest: str) -> PlanningCommitReceipt | None:
        existing = self.store.get_by_idempotency_key(request.idempotency_key)
        if existing is None:
            return None
        if existing.request_fingerprint != digest:
            return self._reject(Code.DUPLICATE_CONFLICT, "idempotency key binds different content")
        # Historical acceptance, never a fresh execution permit.
        return PlanningCommitReceipt(commitId=existing.commit_id,
            commitmentRevision=existing.commitment_revision, status="IDEMPOTENT_REPLAY")

    def _validate_sources(self, sources: FrozenPlanningSources) -> PlanningCommitRejection | None:
        current = self.provider.get_current_sources(sources.mission_id)
        current = FrozenPlanningSources.model_validate(current.model_dump(mode="json", by_alias=True))
        checks = (
            (current.mission_id != sources.mission_id or current.mission_revision != sources.mission_revision,
             Code.STALE_MISSION),
            (current.plan_version != sources.plan_version, Code.STALE_PLAN),
            (current.graph_version != sources.graph_version, Code.STALE_GRAPH),
            (current.observation_id != sources.observation_id
             or current.observation_fingerprint != sources.observation_fingerprint, Code.STALE_OBSERVATION),
            (current.strategy_fingerprint != sources.strategy_fingerprint, Code.STALE_STRATEGY),
        )
        for stale, code in checks:
            if stale:
                return self._reject(code, "trusted planning sources changed")
        return None

    def validate_sources(self, sources: FrozenPlanningSources | Mapping) -> PlanningCommitRejection | None:
        """Read-only preflight; accept() always repeats it inside its guarded operation."""
        try:
            if isinstance(sources, FrozenPlanningSources):
                sources = sources.model_dump(mode="json", by_alias=True)
            sources = FrozenPlanningSources.model_validate(sources)
        except ValidationError:
            return self._reject(Code.INVALID_PROPOSAL, "invalid frozen planning sources")
        try:
            with self.provider.planning_guard(sources.mission_id):
                return self._validate_sources(sources)
        except Exception:
            return self._reject(Code.AUTHORITY_DENIED, "trusted planning state unavailable")

    def accept(self, request: PlanningCommitRequest | Mapping) -> PlanningCommitReceipt:
        try:
            request = self._request(request)
        except ValidationError:
            return self._reject(Code.INVALID_PROPOSAL, "invalid planning commit request")
        try:
            return self._accept(request)
        except Exception:
            return self._reject(Code.STORAGE_UNAVAILABLE, "planning acceptance storage unavailable")

    def _accept(self, request: PlanningCommitRequest) -> PlanningCommitReceipt:
        # Bind every accepted field, not just the claimed proposal fingerprint.
        payload = request.model_dump(mode="json", by_alias=True, exclude={"idempotency_key"})
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode()).hexdigest()
        with self.store._transaction():
            record = None
            parent = None
            try:
                with self.provider.planning_guard(request.sources.mission_id):
                    if self.provider.authorize(request) is not True:
                        return self._reject(Code.AUTHORITY_DENIED, "planning acceptance not authorized")
                    replay = self._replay(request, digest)
                    if replay is not None:
                        return replay
                    problem = self._validate_sources(request.sources)
                    if problem is not None:
                        return problem
                    problem = self.provider.validate_proposal(request)
                    if problem is not None:
                        if not isinstance(problem, PlanningCommitRejection):
                            return self._reject(Code.INVALID_PROPOSAL, "invalid trusted proposal validation result")
                        return PlanningCommitRejection.model_validate(problem.model_dump(mode="json", by_alias=True))
                    # Capture every provider-owned payload/provenance before
                    # closing the source/auth fences. These reads can perform IO.
                    proposal_payload = None
                    if self.store.requires_durable_payload:
                        if request.proposal_type not in {"initial_plan", "plan_revision", "graph_revision"}:
                            return self._reject(Code.INVALID_PROPOSAL, "unsupported durable proposal type")
                        if request.expected_commitment_revision is None:
                            return self._reject(Code.INVALID_PROPOSAL, "durable acceptance requires a commitment base")
                        proposal_payload = self.provider.get_proposal_payload(request)
                        if proposal_payload is None:
                            return self._reject(Code.INVALID_PROPOSAL, "durable proposal content is required")
                    source_provenance = (self.provider.get_source_provenance(request)
                        if callable(getattr(self.provider, "get_source_provenance", None)) else None)
                    if (getattr(self.provider, "requires_versioned_initial_sources", False)
                            and not isinstance(source_provenance, InitialPlanningSourceProvenance)):
                        return self._reject(Code.INVALID_PROPOSAL, "versioned initial source evidence required")
                    # Also catches callbacks that changed state while capturing.
                    problem = self._validate_sources(request.sources)
                    if problem is not None:
                        return problem
                    if self.provider.authorize(request) is not True:
                        return self._reject(Code.AUTHORITY_DENIED, "planning acceptance authority changed")
                    # RLock permits same-thread provider callbacks to reenter a
                    # service sharing this store. Never overwrite their binding.
                    replay = self._replay(request, digest)
                    if replay is not None:
                        return replay
                    parent = self.store.latest(request.sources.mission_id)
                    revision = parent.commitment_revision if parent else 0
                    if (request.expected_commitment_revision is not None
                            and request.expected_commitment_revision != revision):
                        return self._reject(Code.STALE_COMMITMENT, "accepted planning head changed")
                    record = PlanningCommitRecord(commitId="pcommit_" + uuid4().hex,
                        missionId=request.sources.mission_id,
                        parentCommitId=parent.commit_id if parent else None,
                        commitmentRevision=parent.commitment_revision + 1 if parent else 1,
                        proposalId=request.proposal_id, proposalType=request.proposal_type,
                        proposalFingerprint=request.proposal_fingerprint,
                        sourceRevision=request.sources.mission_revision, sources=request.sources,
                        requestedScope=request.requested_scope, requestFingerprint=digest,
                        expectedCommitmentRevision=request.expected_commitment_revision,
                        proposalPayload=proposal_payload,
                        sourceProvenance=source_provenance)
                    receipt = PlanningCommitReceipt(commitId=record.commit_id,
                        commitmentRevision=record.commitment_revision, status="ACCEPTED")
                    self.store._append(request.idempotency_key, record)
            except BaseException as exc:
                # The store lock makes the provisional append invisible to other
                # readers until guard exit; failed exits roll back all indexes.
                if record is not None:
                    self.store._rollback_append(request.idempotency_key, record, parent)
                if not isinstance(exc, Exception):
                    raise
                return self._reject(Code.AUTHORITY_DENIED, "trusted planning authority unavailable")
            return receipt
