"""Authorized, explicit semantic operations; no automatic legacy promotion."""

from collections.abc import Callable

from contracts.mission_semantic import (
    EffectiveMissionSnapshot, MissionSemanticOperation, MissionSemanticRequest,
    SemanticCommit, SemanticOperationReceipt, SemanticOperationResult, SemanticPrincipal,
)
from support.stores.mission_semantic_store import MissionSemanticStore


class MissionSemanticService:
    def __init__(self, *, store: MissionSemanticStore,
                 authorize: Callable[[SemanticPrincipal, str, str], bool]):
        if not callable(authorize):
            raise TypeError("a trusted semantic authorizer is required")
        self.store = store
        self.authorize = authorize

    def _require_access(self, principal: SemanticPrincipal, mission_id: str, action: str) -> SemanticPrincipal:
        principal = SemanticPrincipal.model_validate(principal.model_dump())
        # Only an explicit grant passes. Missing callbacks and accidental None
        # or False results must not silently grant semantic read/write access.
        if self.authorize(principal, mission_id, action) is not True:
            raise PermissionError("semantic access denied")
        return principal

    def commit(self, principal: SemanticPrincipal, request: MissionSemanticRequest) -> SemanticOperationResult:
        request = MissionSemanticRequest.model_validate(request.model_dump())
        principal = self._require_access(principal, request.mission_id, "write")
        operation = MissionSemanticOperation(
            **request.model_dump(), actor_id=principal.actor_id, tenant_id=principal.tenant_id,
        )
        return self.store.commit_semantics(operation)

    def get_effective_snapshot(self, principal: SemanticPrincipal, mission_id: str) -> EffectiveMissionSnapshot:
        self._require_access(principal, mission_id, "read")
        return self.store.get_semantic_snapshot(mission_id)

    def list_commits(self, principal: SemanticPrincipal, mission_id: str) -> list[SemanticCommit]:
        self._require_access(principal, mission_id, "read")
        return self.store.list_semantic_commits(mission_id)

    def get_receipt(self, principal: SemanticPrincipal, mission_id: str, operation_id: str) -> SemanticOperationReceipt | None:
        self._require_access(principal, mission_id, "read")
        return self.store.get_semantic_receipt(mission_id, operation_id)
