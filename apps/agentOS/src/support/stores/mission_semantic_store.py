"""Internal persistence port and deterministic v1 semantic rules.

Public application access belongs to MissionSemanticService. This port, like
WorkflowStore, is trusted infrastructure and does not authenticate request JSON.
"""

from abc import ABC, abstractmethod
import hashlib
import json
from uuid import uuid4

from contracts.mission_semantic import (
    EffectiveMissionSnapshot, MissionSemanticAggregate, MissionSemanticOperation,
    SemanticCommit, SemanticOperationReceipt, SemanticOperationResult,
)
from contracts.workflow import utc_now


class MissionSemanticStore(ABC):
    @abstractmethod
    def commit_semantics(self, operation: MissionSemanticOperation) -> SemanticOperationResult: ...

    @abstractmethod
    def get_semantic_snapshot(self, mission_id: str) -> EffectiveMissionSnapshot: ...

    @abstractmethod
    def list_semantic_commits(self, mission_id: str) -> list[SemanticCommit]: ...

    @abstractmethod
    def get_semantic_receipt(self, mission_id: str, operation_id: str) -> SemanticOperationReceipt | None: ...

    @abstractmethod
    def list_semantic_outbox(self, mission_id: str) -> list[dict]: ...


def semantic_content(value) -> dict:
    # Constraint IDs and references are sets; text is exact, with no semantic
    # equivalence inference, Unicode folding, or whitespace rewriting.
    return {
        "objective": value.objective,
        "constraints": sorted([
            {"constraintId": item.constraint_id, "text": item.text,
             "sourceRefs": sorted(set(item.source_refs))}
            for item in value.constraints
        ], key=lambda item: item["constraintId"]),
        "sourceRefs": sorted(set(value.source_refs)),
    }


def request_fingerprint(operation: MissionSemanticOperation) -> str:
    value = {"fingerprintVersion": 1, "command": "set_semantics",
             "missionId": operation.mission_id, "operationId": operation.operation_id,
             "expectedMissionRevision": operation.expected_mission_revision,
             "actorId": operation.actor_id, "tenantId": operation.tenant_id,
             **semantic_content(operation)}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def replay(operation, fingerprint, receipt):
    if receipt.request_fingerprint == fingerprint:
        return receipt.result.model_copy(deep=True)
    return SemanticOperationResult(
        status="OPERATION_CONFLICT", missionId=operation.mission_id,
        operationId=operation.operation_id, missionRevision=receipt.result.mission_revision,
        expectedMissionRevision=operation.expected_mission_revision,
    )


def prepare_commit(operation, fingerprint, state):
    """Pure decision, called only under the adapter's transaction/lock."""
    revision = state.mission_revision if state else 0
    status = "COMMITTED"
    if operation.expected_mission_revision != revision:
        status = "REVISION_CONFLICT"
    elif state and semantic_content(operation) == semantic_content(state):
        status = "NO_OP"
    commit = None
    if status == "COMMITTED":
        now = utc_now()
        state = MissionSemanticAggregate(
            missionId=operation.mission_id, missionRevision=revision + 1,
            lastCommitId=f"semantic_{uuid4().hex}", updatedAt=now,
            **semantic_content(operation),
        )
        commit = SemanticCommit(
            commitId=state.last_commit_id, missionId=operation.mission_id,
            operationId=operation.operation_id, previousRevision=revision,
            missionRevision=state.mission_revision, actorId=operation.actor_id,
            tenantId=operation.tenant_id, requestFingerprint=fingerprint,
            state=state, createdAt=now,
        )
    result = SemanticOperationResult(
        status=status, missionId=operation.mission_id, operationId=operation.operation_id,
        missionRevision=state.mission_revision if state else 0,
        expectedMissionRevision=operation.expected_mission_revision,
        commitId=commit.commit_id if commit else None,
    )
    return state, commit, SemanticOperationReceipt(requestFingerprint=fingerprint, result=result,
                                                 actorId=operation.actor_id, tenantId=operation.tenant_id)


def semantic_outbox(commit: SemanticCommit) -> dict:
    # Whitelist: no objective/constraint text, principal, or raw Mission input.
    return {"eventId": commit.commit_id, "eventType": "mission.semantic.committed",
            "missionId": commit.mission_id, "commitId": commit.commit_id,
            "missionRevision": commit.mission_revision, "schemaVersion": 1,
            "createdAt": commit.created_at.isoformat()}


def snapshot(mission_id, exists, state):
    refs = state and (state.source_refs or any(item.source_refs for item in state.constraints))
    return EffectiveMissionSnapshot(
        missionId=mission_id,
        status="INITIALIZED" if state else ("UNINITIALIZED" if exists else "MISSION_NOT_FOUND"),
        missionRevision=state.mission_revision if state else 0, state=state,
        sourceStatus="UNVERIFIED" if refs else "NOT_APPLICABLE",
    )
