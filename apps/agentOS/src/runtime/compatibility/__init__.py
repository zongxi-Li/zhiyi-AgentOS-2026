"""Compatibility exports for the shared run lock authority."""

from support.run_locks import GLOBAL_RUN_LOCK_MANAGER, RunLock, RunLockManager

__all__ = ["GLOBAL_RUN_LOCK_MANAGER", "RunLock", "RunLockManager"]
