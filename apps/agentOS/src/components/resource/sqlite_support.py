"""Shared SQLite durability and contention settings for ResourcePlane stores."""

from __future__ import annotations

import sqlite3


def configure_sqlite_connection(
    connection: sqlite3.Connection, *, busy_timeout_ms: int = 30_000
) -> sqlite3.Connection:
    """Apply the same safe local-development settings to every resource DB.

    TODO(architecture-evolution): SQLite remains suitable for local/embedded
    mode only. Production ResourcePlane persistence should use PostgreSQL while
    Redis remains the lease coordinator.
    """
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


__all__ = ["configure_sqlite_connection"]
