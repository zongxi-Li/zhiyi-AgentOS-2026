"""任务元数据的进程内存储接口实现。"""

from typing import Any


class TaskStore:
    """小型内存仓库，便于迁移期替换为持久化适配器。"""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}

    def save(self, task_id: str, payload: dict[str, Any]) -> None:
        self._tasks[task_id] = dict(payload)

    def get(self, task_id: str) -> dict[str, Any] | None:
        item = self._tasks.get(task_id)
        return dict(item) if item is not None else None

    # TODO: 接入 SQLite 或事务型数据库后，实现跨进程一致性与版本冲突控制。
