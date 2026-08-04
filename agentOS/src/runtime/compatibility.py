"""为 AgentOS 运行时变更提供进程内的按运行实例互斥锁。

第一阶段运行时图 MVP 明确为单进程实现；控制器与生命周期操作必须共享
同一锁命名空间。本锁不是分布式锁，也不能替代数据库的比较并交换机制。
"""

from __future__ import annotations

from threading import Lock


class RunLock:
    """封装单个运行实例的短临界区锁，支持同步与异步入口共用互斥语义。"""
    """Short critical-section lock usable by async and legacy sync entry points."""

    def __init__(self) -> None:
        self._lock = Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._lock.release()

    async def __aenter__(self):
        self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self._lock.release()


class RunLockManager:
    """维护运行实例到锁的进程内映射；同一 run_id 永远复用同一把锁。"""
    """Own one short-section lock shared by async and legacy sync run paths."""

    def __init__(self) -> None:
        self._locks: dict[str, RunLock] = {}
        self._registry_lock = Lock()

    def lock_for(self, run_id: str) -> RunLock:
        """按规范化 run_id 返回锁；注册表锁保护创建过程，避免并发生成两把锁。"""
        """Return the process-wide lock associated with ``run_id``."""

        normalized = str(run_id or "").strip()
        if not normalized:
            raise ValueError("run_id is required")
        with self._registry_lock:
            lock = self._locks.get(normalized)
            if lock is None:
                lock = RunLock()
                self._locks[normalized] = lock
            return lock


GLOBAL_RUN_LOCK_MANAGER = RunLockManager()


__all__ = ["RunLockManager", "GLOBAL_RUN_LOCK_MANAGER"]
