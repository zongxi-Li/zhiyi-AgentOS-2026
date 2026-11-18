"""Process-local evidence and policy store with atomic publication under one lock."""
from threading import RLock

from contracts.evolution import EvolutionPolicyVersion
from components.evolution.domain.policy import publication_receipt, require_replay, require_transition
from components.evolution.ports.store import EvolutionVersionConflict


class InMemoryEvolutionStore:
    def __init__(self) -> None:
        self._versions = {0: EvolutionPolicyVersion(version=0, policy={})}
        self._active = 0
        self._trajectories, self._evaluations, self._proposals, self._receipts = {}, {}, {}, {}
        self._lock = RLock()

    def active(self):
        with self._lock:
            return self._versions[self._active].model_copy(deep=True)

    def get(self, version):
        return self._get(self._versions, version, "policy version")

    def list_versions(self):
        with self._lock:
            return [self._versions[key].model_copy(deep=True) for key in sorted(self._versions)]

    def create(self, value, *, expected_active):
        with self._lock:
            self._check_version(value, expected_active)
            self._insert_version(value)
            return value.model_copy(deep=True)

    def _check_version(self, value, expected_active):
        if expected_active != self._active or value.base_version != expected_active:
            raise EvolutionVersionConflict(f"expected active evolution version {expected_active}, current {self._active}")
        if value.version in self._versions or value.version != self._active + 1:
            raise EvolutionVersionConflict(f"invalid next evolution version: {value.version}")

    def _insert_version(self, value):
        self._versions[self._active] = self._versions[self._active].model_copy(update={"status": "superseded"})
        self._versions[value.version] = value.model_copy(deep=True)
        self._active = value.version

    def commit_approval(self, value, proposal, *, expected_active):
        with self._lock:
            receipt = self._receipts.get(proposal.proposal_id)
            if receipt is not None:
                require_replay(receipt, proposal, proposal.reviewed_by)
                return receipt.model_copy(deep=True)
            self._check_version(value, expected_active)
            pending = self.get_proposal(proposal.proposal_id)
            receipt = publication_receipt(self.active(), pending, proposal, value,
                [self.get_evaluation(key) for key in pending.trajectory_ids])
            # Prepare all copies before any visible mutation.
            approved, stored_receipt = proposal.model_copy(deep=True), receipt.model_copy(deep=True)
            self._insert_version(value)
            self._proposals[proposal.proposal_id] = approved
            self._receipts[proposal.proposal_id] = stored_receipt
            return receipt

    def get_receipt(self, proposal_id):
        return self._get(self._receipts, proposal_id, "publication receipt")

    def save_trajectory(self, value):
        return self._save_immutable(self._trajectories, value.trajectory_id, value)

    def get_trajectory(self, trajectory_id):
        return self._get(self._trajectories, trajectory_id, "trajectory")

    def save_evaluation(self, value):
        return self._save_immutable(self._evaluations, value.trajectory_id, value)

    def get_evaluation(self, trajectory_id):
        return self._get(self._evaluations, trajectory_id, "evaluation")

    def save_proposal(self, value):
        with self._lock:
            try:
                require_transition(self._proposals.get(value.proposal_id), value)
            except ValueError as exc:
                raise EvolutionVersionConflict(str(exc)) from exc
            self._proposals[value.proposal_id] = value.model_copy(deep=True)
            return value.model_copy(deep=True)

    def get_proposal(self, proposal_id):
        return self._get(self._proposals, proposal_id, "proposal")

    def _save_immutable(self, values, key, value):
        with self._lock:
            if key in values and values[key] != value:
                raise EvolutionVersionConflict(f"{key} already exists with different content")
            values[key] = value.model_copy(deep=True)
            return value.model_copy(deep=True)

    def _get(self, values, key, kind):
        with self._lock:
            try:
                return values[key].model_copy(deep=True)
            except KeyError as exc:
                raise KeyError(f"unknown evolution {kind}: {key}") from exc
