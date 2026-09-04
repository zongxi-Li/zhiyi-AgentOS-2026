"""为 AgentOS 运行时变更提供进程内的按运行实例互斥锁。

第一阶段运行时图 MVP 明确为单进程实现；控制器与生命周期操作必须共享
同一锁命名空间。本锁不是分布式锁，也不能替代数据库的比较并交换机制。
"""

from __future__ import annotations

from threading import Lock


class RunLock:
    """封装单个运行实例的短临界区锁，供同步和异步入口共享互斥语义。

    上下文管理器只保护进程内短操作，不是分布式锁；异常退出时仍释放锁，调用方
    必须避免在临界区内执行网络或长时间 await，以免阻塞同一运行的后续状态写入。
    """

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
    """维护运行实例到锁的进程内映射；同一 ``run_id`` 始终复用同一把锁。"""

    def __init__(self) -> None:
        self._locks: dict[str, RunLock] = {}
        self._registry_lock = Lock()

    def lock_for(self, run_id: str) -> RunLock:
        """按规范化 ``run_id`` 返回锁，并用注册表锁原子地创建缺失条目。

        空标识会抛出 ``ValueError``；返回的锁只在当前进程有效，调用方负责缩短
        临界区以避免阻塞其他针对同一运行的操作。
        """

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
