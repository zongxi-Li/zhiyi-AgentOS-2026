"""Single-instance guard for the SQLite-backed AgentOS runtime."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import IO


# One normalized Workflow database per process while held. The OS guard remains
# directory-wide, so separate processes in the same data directory also conflict.
_LOCK_HANDLE: IO[str] | None = None
_LOCK_DATABASE: Path | None = None
_LOCK_VALID = False
LOGGER = logging.getLogger(__name__)


def _unlock(handle: IO[str]) -> None:
    """Drop the OS-level lock explicitly; close() below releases it anyway."""
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Closing the descriptor releases the lock on both platforms.
        LOGGER.warning("instance lock explicit unlock failed", exc_info=True)


def _drop_handle(handle: IO[str]) -> None:
    """Unlock and close one handle; raise so a failed release stays observable."""
    try:
        _unlock(handle)
    finally:
        handle.close()


def acquire_workflow_instance_lock(db_path: str) -> IO[str]:
    global _LOCK_HANDLE, _LOCK_DATABASE, _LOCK_VALID
    database = Path(db_path).resolve()
    lock_path = database.parent / "runtime.instance.lock"
    if _LOCK_HANDLE is not None:
        if not _LOCK_VALID or _LOCK_HANDLE.closed:
            raise RuntimeError("workflow instance lock state is uncertain or invalid; release must succeed before retry")
        if _LOCK_DATABASE != database:
            raise RuntimeError(
                "instance lock already held for a different workflow database: "
                f"{_LOCK_DATABASE}"
            )
        return _LOCK_HANDLE
    workers = int(os.getenv("UVICORN_WORKERS", os.getenv("WEB_CONCURRENCY", "1")))
    if workers != 1:
        raise RuntimeError("SQLite WorkflowStore requires exactly one Uvicorn worker")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if handle.read(1) == "":
                handle.seek(0)
                handle.write("0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        try:
            handle.close()
        except Exception:
            _LOCK_HANDLE = handle
            _LOCK_DATABASE = database
            _LOCK_VALID = False
            LOGGER.warning("refused acquisition: handle close failed", exc_info=True)
        raise RuntimeError(f"another AgentOS runtime owns {lock_path}") from exc
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
    except OSError:
        # The handle owns the OS lock already; dropping it here is the only
        # way a failed acquisition leaves nothing behind.
        # Publish an invalid cleanup reference before release: close may fail.
        _LOCK_HANDLE = handle
        _LOCK_DATABASE = database
        _LOCK_VALID = False
        try:
            release_workflow_instance_lock()
        except Exception:
            LOGGER.warning("failed acquisition cleanup failed", exc_info=True)
        raise
    _LOCK_HANDLE = handle
    _LOCK_DATABASE = database
    _LOCK_VALID = True
    return handle


def release_workflow_instance_lock() -> None:
    """Release the application-owned process lock during an orderly shutdown."""
    global _LOCK_HANDLE, _LOCK_DATABASE, _LOCK_VALID
    handle = _LOCK_HANDLE
    if handle is None:
        return
    # Invalidate BEFORE any OS operation. A surviving handle is only a cleanup
    # reference and must never authorize a later Runtime assembly.
    _LOCK_VALID = False
    try:
        if not handle.closed:
            _drop_handle(handle)
    except Exception:
        # Either the lock survives or explicit unlock succeeded. Both cases
        # refuse acquisition until the descriptor has definitely closed.
        LOGGER.warning("instance lock release failed; state uncertain", exc_info=True)
        raise
    _LOCK_HANDLE = None
    _LOCK_DATABASE = None


__all__ = ["acquire_workflow_instance_lock", "release_workflow_instance_lock"]
