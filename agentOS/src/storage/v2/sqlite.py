"""新 ACG 存储的连接、Schema 和事务边界。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator

from .schema import SCHEMA_SQL


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
            self._connection.executescript(SCHEMA_SQL)
            self._connection.commit()

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


__all__ = ["SQLiteV2Storage"]
