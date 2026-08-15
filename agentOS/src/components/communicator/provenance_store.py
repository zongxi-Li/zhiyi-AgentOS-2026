"""通信血缘账本的独立 SQLite 持久化。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .provenance import ProvenanceIntegrityError, ProvenanceLedger, _Event


class SQLiteProvenanceStore:
    """仅保存已封存的血缘事件 JSON，并在恢复时强制校验哈希链。

    本仓库与 WorkflowStore、checkpoint 和正文引用仓库分离。它从不接收 slot、
    ContextPack、Agent 输出、prompt 或工具参数，只接收 ``ProvenanceLedger`` 已经
    裁剪并加上哈希链的事件模型。
    """

    def __init__(self, *, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS acg_provenance_events (
                run_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (run_id, event_id)
            )"""
        )
        self._connection.commit()

    def append(self, event: _Event) -> None:
        """追加一个已封存事件；重复标识只接受完全相同的不可变 JSON。"""
        payload = event.model_dump(by_alias=True, mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT event_json FROM acg_provenance_events WHERE run_id = ? AND event_id = ?",
                (event.run_id, event.event_id),
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO acg_provenance_events(run_id, event_id, event_json) VALUES (?, ?, ?)",
                    (event.run_id, event.event_id, encoded),
                )
            elif str(row[0]) != encoded:
                raise ProvenanceIntegrityError(
                    f"provenance event already exists with different payload: {event.event_id}"
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def load_ledger(self, *, run_id: str, task_id: str) -> ProvenanceLedger:
        """加载 run 的事件，重建并验证哈希链后返回可继续追加的账本。"""
        rows = self._connection.execute(
            "SELECT event_json FROM acg_provenance_events WHERE run_id = ? ORDER BY event_id",
            (run_id,),
        ).fetchall()
        events: list[dict[str, Any]] = [json.loads(str(row[0])) for row in rows]
        return ProvenanceLedger.from_events(
            run_id=run_id,
            task_id=task_id,
            events=events,
            event_sink=self.append,
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        self._connection.close()


__all__ = ["SQLiteProvenanceStore"]
