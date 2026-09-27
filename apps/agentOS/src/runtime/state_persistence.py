"""Persistence boundary for reference-only ACG execution state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import hashlib
import json

from components.executor import ACGExecutionState
from components.recovery.checkpoint import ACGCheckpointStore
from contracts.workflow import RuntimeRunRecord, utc_now
from support.stores.workflow_store import WorkflowStore


class ACGStatePersistenceService:
    """Persist ACG projections and deterministic checkpoints without policy decisions."""

    def __init__(
        self,
        *,
        checkpoint_store: ACGCheckpointStore,
        workflow_store: WorkflowStore,
        after_checkpoint_hook: Callable[[], None] | None = None,
    ) -> None:
        self.checkpoint_store = checkpoint_store
        self.workflow_store = workflow_store
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


__all__ = ["ACGStatePersistenceService"]
