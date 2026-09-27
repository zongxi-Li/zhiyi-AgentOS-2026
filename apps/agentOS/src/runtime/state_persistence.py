"""Persistence boundary for reference-only ACG execution state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import hashlib
import json
from typing import Any

from components.executor import ACGExecutionState
from contracts.workflow import RuntimeRunRecord, utc_now
from runtime.ports import CollaboratorAccess, RuntimeCollaborators


def acg_execution_state_from_run(run: RuntimeRunRecord) -> ACGExecutionState:
    """Read the ACG state subset from a Run snapshot's wider state map."""

    raw = run.execution_state if isinstance(run.execution_state, dict) else {}
    state_data: dict[str, Any] = {}
    for field_name, field in ACGExecutionState.model_fields.items():
        alias = field.alias or field_name
        if alias in raw:
            state_data[alias] = raw[alias]
        elif field_name in raw:
            state_data[alias] = raw[field_name]
    state_data.setdefault("runId", run.run_id)
    return ACGExecutionState.model_validate(state_data)


class ACGStatePersistenceService(CollaboratorAccess):
    """Persist ACG projections and deterministic checkpoints without policy decisions."""

    def __init__(
        self,
        *,
        collaborators: RuntimeCollaborators,
        after_checkpoint_hook: Callable[[], None] | None = None,
    ) -> None:
        self.ports = collaborators
        self.after_checkpoint_hook = after_checkpoint_hook

    def persist(
        self,
        run: RuntimeRunRecord,
        state: ACGExecutionState,
        *,
        projection_changed: bool | None = None,
    ) -> None:
        """Project reference-only state into the Run and persist it."""

        previous_state = dict(run.execution_state)
        previous_completed = list(run.completed_step_ids)
        previous_active = list(run.active_step_ids)
        state_data = state.model_dump(by_alias=True, mode="json")
        run.execution_state.update(state_data)
        run.completed_step_ids = list(state.completed_step_ids)
        run.active_step_ids = list(state.active_step_ids)
        if projection_changed is None:
            projection_changed = (
                any(previous_state.get(key) != value for key, value in state_data.items())
                or previous_completed != run.completed_step_ids
                or previous_active != run.active_step_ids
            )
        if projection_changed:
            run.runtime_revision += 1
            self._touch_run_projection(run)
        self.workflow_store.save_run(run)

    def save_checkpoint(
        self,
        run: RuntimeRunRecord,
        state: ACGExecutionState,
    ) -> str:
        """Save the next deterministic checkpoint with the existing CAS rule."""

        expected_version = self.checkpoint_store.latest_version(run_id=run.run_id)
        checkpoint_data = state.model_dump(by_alias=True, mode="json")
        checkpoint_data["checkpointId"] = None
        encoded = json.dumps(
            checkpoint_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        checkpoint_id = (
            "acgckpt_"
            + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
        )
        state.checkpoint_id = checkpoint_id
        saved = self.checkpoint_store.save(
            run_id=run.run_id,
            checkpoint_id=checkpoint_id,
            state=state.model_dump(by_alias=True, mode="json"),
            expected_version=expected_version,
        )
        if self.after_checkpoint_hook is not None:
            self.after_checkpoint_hook()
        return saved

    @staticmethod
    def _touch_run_projection(run: RuntimeRunRecord) -> None:
        now = utc_now()
        if now <= run.updated_at:
            now = run.updated_at + timedelta(microseconds=1)
        run.updated_at = now


__all__ = ["ACGStatePersistenceService", "acg_execution_state_from_run"]
