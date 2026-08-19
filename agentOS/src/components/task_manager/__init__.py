"""Public task-manager boundary backed by one lifecycle implementation."""

from .service import TaskManager, TaskManagerService

__all__ = ["TaskManager", "TaskManagerService"]
