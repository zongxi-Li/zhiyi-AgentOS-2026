from __future__ import annotations

from storage.v2 import CURRENT_SCHEMA_VERSION, SQLiteV2Storage


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
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert {
        "missions",
        "semantic_tasks",
        "acg_blueprints",
        "workflow_runs_v2",
        "attempts",
        "step_executions",
        "task_bindings",
        "blueprint_node_bindings",
        "execution_bindings",
        "artifacts",
        "run_artifact_bindings",
        "provenance_links",
        "lifecycle_projection_events",
    }.issubset(tables)
    assert "tasks" not in tables
    assert "runs" not in tables
    assert foreign_keys == 1
    # 恒久不变式：库内 user_version 必须与声明的 CURRENT_SCHEMA_VERSION 一致，
    # 任何一侧漂移（迁移漏设版本、常量误改）都在这里炸。
    assert schema_version == CURRENT_SCHEMA_VERSION
    # 刻意变更钉：升版必须伴随真实迁移与迁移记录，同一次变更内更新本字面量；
    # 本断言失败时先确认迁移集，再改数字，不要把它当作可放行的基线失败。
    assert CURRENT_SCHEMA_VERSION == 3
