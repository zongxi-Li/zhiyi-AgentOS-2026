"""新 ACG 存储的连接、Schema 和事务边界。"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator

from .schema import SCHEMA_SQL


CURRENT_SCHEMA_VERSION = 3


class SQLiteV2Storage:
    """持有独立连接；不会读取或修改旧 tasks/runs 表。"""

    def __init__(self, db_path: str | Path = "data/agentos_v2.sqlite3") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        if self.db_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
        with self._lock:
            # Older V2 databases were initialized by CREATE IF NOT EXISTS only.
            # Add compatibility columns before running the current schema script,
            # because its indexes reference the canonical semantic key.
            self._ensure_legacy_columns()
            self._connection.executescript(SCHEMA_SQL)
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if version < CURRENT_SCHEMA_VERSION:
                self._backfill_unambiguous_semantic_keys()
                self._connection.execute(
                    f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}"
                )
            self._connection.commit()

    def _ensure_legacy_columns(self) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'semantic_tasks'"
        ).fetchone()
        if row is None:
            return
        columns = {
            str(item[1])
            for item in self._connection.execute("PRAGMA table_info(semantic_tasks)").fetchall()
        }
        if "semantic_key" not in columns:
            self._connection.execute(
                "ALTER TABLE semantic_tasks ADD COLUMN semantic_key TEXT"
            )

    def _backfill_unambiguous_semantic_keys(self) -> None:
        """Promote only provably unique legacy planner keys.

        A repeated metadata key may represent historical semantic drift. It is
        intentionally left as a legacy row instead of being guessed or merged.
        """
        rows = self._connection.execute(
            "SELECT task_id, mission_id, metadata_json, semantic_key "
            "FROM semantic_tasks WHERE semantic_key IS NULL"
        ).fetchall()
        candidates: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            key = metadata.get("plannerSemanticKey") if isinstance(metadata, dict) else None
            if isinstance(key, str) and key.strip() and not any(character.isspace() for character in key):
                candidates.setdefault((str(row["mission_id"]), key), []).append(
                    str(row["task_id"])
                )
        for (_mission_id, key), task_ids in candidates.items():
            if len(task_ids) == 1:
                self._connection.execute(
                    "UPDATE semantic_tasks SET semantic_key = ? WHERE task_id = ?",
                    (key, task_ids[0]),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            nested = self._connection.in_transaction
            try:
                if not nested:
                    self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                if not nested:
                    self._connection.commit()
            except Exception:
                if not nested:
                    self._connection.rollback()
                raise

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._connection

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteV2Storage":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["CURRENT_SCHEMA_VERSION", "SQLiteV2Storage"]
