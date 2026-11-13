"""Durable workspace invalidation watermarks and commit-only local wakeups.

The Identity and Runtime databases each maintain a mission-local counter. Their
sum is a monotone lower watermark, not a transactional snapshot or an ETag.
Triggers update counters in the source transaction, including non-runtime writes.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import sqlite3
from threading import Lock


class WorkspaceChangeHub:
    def __init__(self):
        self._lock = Lock()
        self._subscribers = set()

    @asynccontextmanager
    async def subscribe(self):
        loop, queue = asyncio.get_running_loop(), asyncio.Queue(maxsize=1)
        item = (loop, queue)
        with self._lock:
            self._subscribers.add(item)
        try:
            yield queue
        finally:
            with self._lock:
                self._subscribers.discard(item)

    def notify(self):
        with self._lock:
            subscribers = tuple(self._subscribers)
        for loop, queue in subscribers:
            def wake(queue=queue):
                if queue.empty():
                    queue.put_nowait(None)
            try:
                loop.call_soon_threadsafe(wake)
            except RuntimeError:
                pass  # The owning request/event loop has already closed.


workspace_changes = WorkspaceChangeHub()


class WorkspaceConnection(sqlite3.Connection):
    """Wake observers only after a successful SQLite transaction commit."""
    _notified_changes = 0

    def _notify_committed(self):
        if self.total_changes != self._notified_changes:
            self._notified_changes = self.total_changes
            workspace_changes.notify()

    def commit(self):
        super().commit()
        self._notify_committed()

    def rollback(self):
        super().rollback()
        self._notified_changes = self.total_changes

    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        if exc_type is None:
            self._notify_committed()
        else:
            self._notified_changes = self.total_changes
        return result


def projection_revision(conn, mission_id: str) -> int:
    row = conn.execute("SELECT revision FROM workspace_projection_versions WHERE mission_id=?", (mission_id,)).fetchone()
    return int(row[0]) if row else 0


def install_revision_triggers(conn, sources: dict[str, str]):
    """Install additive, idempotent bookkeeping; expressions use {row} alias."""
    conn.execute("""CREATE TABLE IF NOT EXISTS workspace_projection_versions (
        mission_id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision >= 0))""")
    for table, expression in sources.items():
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        if not columns:
            continue
        for operation, alias in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            mission = expression.format(row=alias)
            selection = mission if mission.startswith("SELECT ") else f"SELECT {mission} AS mission_id"
            changed = " OR ".join(f'NEW."{column}" IS NOT OLD."{column}"' for column in columns)
            condition = f" WHEN {changed}" if operation == "UPDATE" else ""
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS workspace_revision_{table}_{operation.lower()}
                AFTER {operation} ON "{table}"{condition}
                BEGIN
                    INSERT INTO workspace_projection_versions(mission_id, revision)
                    SELECT mission_id, 1 FROM ({selection}) WHERE mission_id IS NOT NULL
                    ON CONFLICT(mission_id) DO UPDATE SET revision=revision+1;
                END""")


IDENTITY_SOURCES = {
    **{name: "{row}.mission_id" for name in (
        "missions", "semantic_tasks", "task_plans", "task_plan_nodes", "task_plan_relations",
        "acg_blueprints", "workflow_runs_v2", "mission_input_attachments", "artifacts")},
    **{name: "SELECT mission_id FROM workflow_runs_v2 WHERE run_id={row}.run_id" for name in (
        "attempts", "step_executions", "run_artifact_bindings", "run_input_attachments")},
    **{name: "SELECT mission_id FROM acg_blueprints WHERE blueprint_id={row}.blueprint_id" for name in (
        "task_bindings", "blueprint_node_bindings")},
    "input_attachments": "SELECT mission_id FROM mission_input_attachments WHERE attachment_id={row}.attachment_id",
    "execution_bindings": "SELECT r.mission_id FROM attempts a JOIN workflow_runs_v2 r ON r.run_id=a.run_id WHERE a.attempt_id={row}.attempt_id",
}

RUNTIME_SOURCES = {
    **{name: "{row}.mission_id" for name in ("tasks", "runs", "mission_semantic_state")},
}
