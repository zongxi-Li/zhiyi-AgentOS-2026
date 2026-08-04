"""任务管理部件只依赖的跨边界数据合同。"""

from contracts.task import TaskConstraint, TaskLifecycleEvent

__all__ = ["TaskConstraint", "TaskLifecycleEvent"]
