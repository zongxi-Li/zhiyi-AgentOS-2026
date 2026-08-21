from __future__ import annotations

from storage.v2 import SQLiteV2Storage


def test_v2_schema_is_independent_and_complete() -> None:
    with SQLiteV2Storage(":memory:") as storage:
        with storage.read() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert {
        "user_tasks",
        "task_nodes",
        "acg_blueprints",
        "workflow_runs_v2",
        "attempts",
        "step_executions",
        "task_node_bindings",
        "blueprint_node_bindings",
        "execution_bindings",
        "provenance_links",
    }.issubset(tables)
    assert "tasks" not in tables
    assert "runs" not in tables
    assert foreign_keys == 1
