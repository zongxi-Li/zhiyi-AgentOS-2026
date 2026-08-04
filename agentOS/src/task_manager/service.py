"""任务管理的公共 Facade。"""

from typing import Any

from .algorithms import task_complexity
from .store import TaskStore


class TaskManagerService:
    """提供创建和读取任务的最小稳定 API。"""

    def __init__(self, store: TaskStore | None = None) -> None:
        self._store = store or TaskStore()

    def register(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """登记任务，并返回含可解释复杂度的不可变副本。"""
        item = dict(payload)
        item.setdefault("complexity", task_complexity(len(item.get("constraints", []))))
        self._store.save(task_id, item)
        return item

    def get(self, task_id: str) -> dict[str, Any] | None:
        """读取任务快照，不暴露仓库内的可变对象。"""
        return self._store.get(task_id)
