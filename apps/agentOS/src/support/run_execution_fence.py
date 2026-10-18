"""OS mutual exclusion for a Run's executor and graph activation critical cut.

This is not an execution permit or a durable lease. Closing the descriptor (or
process death) releases the lock. Unsettled durable receipts must independently
block activation after a process dies. Never unlink live lock files: doing so
would create distinct lock identities for the same Run.
"""
import errno
import hashlib
import os
from pathlib import Path


class RunFenceBusy(ValueError):
    pass


class RunExecutionFence:
    def __init__(self, handle):
        self.handle = handle

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            handle.close()  # OS releases the byte-range/flock lock with its handle.

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def acquire_run_fence(db_path, run_id):
    database = Path(db_path).resolve()
    identity = os.path.normcase(str(database)) + "\0" + run_id
    name = ".run-fence-" + hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".lock"
    handle = None
    try:
        handle = (database.parent / name).open("a+b")
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise RunFenceBusy(f"run {run_id} already has an active execution or activation") from exc
            raise
        return RunExecutionFence(handle)
    except BaseException as exc:
        if handle is not None:
            handle.close()
        if isinstance(exc, OSError):
            raise RuntimeError("Run execution fence unavailable; refusing the cut") from exc
        raise
