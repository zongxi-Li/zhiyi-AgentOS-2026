"""把执行运行时（workflows.sqlite3）中缺失身份投影的 Run 回填进 identity_v2。

背景：延迟规划（planningDeferred）的重跑 Run 在规划编译失败时不会产生任何
lifecycle outbox 事件，导致身份图（workspace / 任务历史的权威读模型）缺少该 Run，
前端任务工作台的 Run 列表与运行时全局列表数量不一致。

本脚本只做**补账**，不做修复规划数据：仅回填终态（failed/succeeded/cancelled/
superseded）且能从同任务既有蓝图解析出 blueprint_id 的 Run；蓝图无来源或仍在
活跃态的 Run 一律跳过并报告。回填行的 metadata 会写入 backfill 溯源标记，
与正常投影行明确区分。

用法（在 ai-service 容器内执行）:
    python3 /app/ops_scripts/backfill_identity_runs.py            # 只读预览
    python3 /app/ops_scripts/backfill_identity_runs.py --apply    # 实际写入
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUS_MAP = {
    "failed": "failed",
    "completed": "succeeded",
    "cancelled": "cancelled",
    "superseded": "superseded",
}
ACTIVE_STATUSES = {"pending", "planning", "running", "retrying", "waiting_review", "queued"}


def _iso(value: str | None) -> str | None:
    """统一为 +00:00 后缀，与既有投影行的时间格式保持一致。"""
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return normalized


def _load_runtime_runs(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT run_id, mission_id, status, updated_at, payload FROM runs").fetchall()
    finally:
        con.close()
    runs = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        runs.append({
            "run_id": row["run_id"],
            "mission_id": row["mission_id"],
            "status": str(row["status"] or ""),
            "updated_at": row["updated_at"],
            "payload": payload,
        })
    return runs


def _backfill_plan(runs: list[dict], identity: sqlite3.Connection) -> tuple[list[dict], list[str]]:
    existing = {
        row[0] for row in identity.execute("SELECT run_id FROM workflow_runs_v2")
    }
    missions = {
        row[0] for row in identity.execute("SELECT mission_id FROM missions")
    }
    blueprints_by_run: dict[str, str] = {
        row[0]: row[1]
        for row in identity.execute("SELECT run_id, blueprint_id FROM workflow_runs_v2")
    }
    blueprints_by_mission: dict[str, list[str]] = {}
    for row in identity.execute("SELECT run_id, mission_id, blueprint_id FROM workflow_runs_v2"):
        blueprints_by_mission.setdefault(row[1], []).append(row[2])

    plan: list[dict] = []
    skipped: list[str] = []
    for run in runs:
        run_id = run["run_id"]
        if run_id in existing:
            continue
        if run["mission_id"] not in missions:
            skipped.append(f"{run_id}: mission {run['mission_id']} 不在身份图中，跳过")
            continue
        status = STATUS_MAP.get(run["status"])
        if status is None:
            skipped.append(
                f"{run_id}: 状态 {run['status'] or '未知'} 非终态，交给正常投影/对账，跳过"
            )
            continue
        payload = run["payload"]
        execution_state = payload.get("executionState") or {}
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        blueprint_id = blueprints_by_run.get(str(execution_state.get("parentRunId") or ""))
        if not blueprint_id:
            mission_blueprints = blueprints_by_mission.get(run["mission_id"]) or []
            if len(mission_blueprints) == 1:
                blueprint_id = mission_blueprints[0]
        if not blueprint_id:
            skipped.append(
                f"{run_id}: 无法解析蓝图来源（无父 Run 且任务蓝图不唯一），跳过"
            )
            continue
        created_at = _iso(payload.get("createdAt")) or _iso(run["updated_at"])
        updated_at = _iso(run["updated_at"]) or created_at
        started_at = _iso(payload.get("startedAt"))
        finished_at = _iso(payload.get("finishedAt")) or updated_at if status != "superseded" else None
        if not created_at or not updated_at:
            skipped.append(f"{run_id}: 运行时记录缺少可信时间戳，跳过")
            continue
        plan.append({
            "run_id": run_id,
            "mission_id": run["mission_id"],
            "blueprint_id": blueprint_id,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "metadata": {
                "workflowId": payload.get("workflowId"),
                "parentRunId": execution_state.get("parentRunId"),
                "sourceRunId": execution_state.get("sourceRunId"),
                "rerunReason": execution_state.get("rerunReason"),
                "backfill": {
                    "appliedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "source": "ops/scripts/backfill_identity_runs.py",
                    "runtimeStatus": run["status"],
                    "runtimeError": str(error.get("message") or "")[:300] or None,
                    "note": "planning-deferred rerun failed before planner materialization; runtime-only run backfilled for read-model consistency",
                },
            },
        })
    return plan, skipped


def _apply(plan: list[dict], identity: sqlite3.Connection) -> int:
    identity.execute("PRAGMA foreign_keys = ON")
    applied = 0
    for item in plan:
        cursor = identity.execute(
            """
            INSERT INTO workflow_runs_v2 (
                run_id, mission_id, blueprint_id, status, graph_version,
                started_at, finished_at, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                item["run_id"],
                item["mission_id"],
                item["blueprint_id"],
                item["status"],
                item["started_at"],
                item["finished_at"],
                item["created_at"],
                item["updated_at"],
                json.dumps(item["metadata"], ensure_ascii=False, sort_keys=True),
            ),
        )
        applied += cursor.rowcount
    identity.commit()
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=os.getenv("AGENTOS_DATA_DIR", "/app/data/agentos"),
        help="包含 workflows.sqlite3 与 identity_v2.sqlite3 的目录",
    )
    parser.add_argument("--apply", action="store_true", help="实际写入；缺省为只读预览")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    runtime_db = data_dir / "workflows.sqlite3"
    identity_db = data_dir / "identity_v2.sqlite3"
    for path in (runtime_db, identity_db):
        if not path.exists():
            print(f"缺少数据库文件: {path}", file=sys.stderr)
            return 2

    runs = _load_runtime_runs(runtime_db)
    identity = sqlite3.connect(str(identity_db), timeout=30)
    identity.row_factory = sqlite3.Row
    try:
        plan, skipped = _backfill_plan(runs, identity)
        print(f"运行时 Run 总数: {len(runs)}")
        print(f"待回填: {len(plan)}；跳过: {len(skipped)}")
        for reason in skipped:
            print(f"  [skip] {reason}")
        for item in plan:
            print(
                f"  [plan] {item['run_id']} status={item['status']} "
                f"blueprint={item['blueprint_id']} (继承自父 Run/任务唯一蓝图)"
            )
        if not plan:
            return 0
        if not args.apply:
            print("dry-run 结束；加 --apply 执行写入")
            return 0
        applied = _apply(plan, identity)
        print(f"已回填 {applied} 条 Run 投影")
        return 0
    finally:
        identity.close()


if __name__ == "__main__":
    raise SystemExit(main())
