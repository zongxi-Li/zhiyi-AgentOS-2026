"""Thread-owned SQLite connections for stores used by settled worker tasks."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock, local


class ThreadLocalSQLiteConnections:
    """Keep each thread's transactions on its own connection to one database.

    The constructing thread bootstraps the store schema. Later threads only
    open the existing database in ``mode=rw``; they cannot recreate a missing
    database or run schema setup. Callers must settle workers before ``close``.
    ``check_same_thread=False`` permits that final cleanup from the owning
    store's shutdown thread, never concurrent transactions on one connection.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path).resolve()
        self._local = local()
        self._lock = RLock()
        self._closed = False
        connection = sqlite3.connect(self._path, check_same_thread=False)
        self._local.connection = connection
        self._connections = [connection]

    def connection(self) -> sqlite3.Connection:
        """Return only this thread's connection, opening it once when needed."""
        with self._lock:
            connection = getattr(self._local, "connection", None)
            if connection is not None:
                # Retain the closed handle for shutdown diagnostics on threads
                # that already owned it. SQL still fails with SQLite's normal
                # closed-database error; shutdown never opens another handle.
                return connection
            if self._closed:
                raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
            connection = sqlite3.connect(
                self._path.as_uri() + "?mode=rw", uri=True, check_same_thread=False
            )
            self._local.connection = connection
            self._connections.append(connection)
            return connection

    def close(self) -> None:
        """Close every thread's connection after its tasks have settled."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            errors = []
            for connection in self._connections:
                try:
                    connection.close()
                except sqlite3.Error as exc:
                    errors.append(exc)
            self._connections.clear()
            if errors:
                raise errors[0]
