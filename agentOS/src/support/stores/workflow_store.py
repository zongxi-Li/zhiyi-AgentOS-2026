"""运行时配套任务/运行存储合同，不包含跨部件业务编排实现。"""


from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

from contracts.workflow import AgentTask, WorkflowRun, WorkflowStatus


T = TypeVar("T")


@dataclass(frozen=True)
class WorkflowStorePage(Generic[T]):
    """WorkflowStore 的分页查询结果。"""

    items: tuple[T, ...]
    total: int
    page: int
    page_size: int

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


@dataclass(frozen=True)
class WorkflowRunDeleteResult:
    """删除一次运行及其孤立父任务后的结果；``task_deleted`` 明确是否发生级联删除。"""

    run_id: str
    task_id: str
    task_deleted: bool


class WorkflowRunNotTerminalError(ValueError):
    """在运行未到终态时请求物理删除所抛出的错误，携带运行标识与当前状态。"""

    def __init__(self, run_id: str, status: WorkflowStatus):
        super().__init__(f"workflow run is not terminal: {run_id} ({status.value})")
        self.run_id = run_id
        self.status = status


def paginate_items(items: Sequence[T], *, page: int = 1, page_size: int = 20) -> WorkflowStorePage[T]:
    """按安全页码切分序列。

    页码和页大小下限为 1；保持输入顺序并返回总数，切片复杂度与当前页大小相关。
    """
    safe_page = max(1, page)
    safe_page_size = max(1, page_size)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return WorkflowStorePage(
        items=tuple(items[start:end]),
        total=len(items),
        page=safe_page,
        page_size=safe_page_size,
    )


def status_value(status: WorkflowStatus | str | None) -> str | None:
    """把状态枚举或字符串归一为存储筛选值；``None`` 保持为不筛选。"""
    if status is None:
        return None
    return status.value if isinstance(status, WorkflowStatus) else str(status)


def status_values(statuses: Sequence[WorkflowStatus | str] | None) -> set[str] | None:
    """把状态序列归一为集合；空序列返回 ``None`` 表示不施加多状态筛选。"""
    if not statuses:
        return None
    return {item.value if isinstance(item, WorkflowStatus) else str(item) for item in statuses}


class WorkflowStore(ABC):
    """AgentTask 和 WorkflowRun 状态的持久化边界。"""

    @abstractmethod
    def save_task(self, task: AgentTask) -> None:
        """持久化任务；实现应定义覆盖和并发语义。"""
        raise NotImplementedError

    @abstractmethod
    def get_task(self, task_id: str) -> AgentTask:
        """按标识读取任务；不存在时应抛出 ``KeyError``。"""
        raise NotImplementedError

    @abstractmethod
    def save_run(self, run: WorkflowRun) -> None:
        """持久化运行；实现必须维护终态不可被旧快照覆盖的不变量。"""
        raise NotImplementedError

    @abstractmethod
    def get_run(self, run_id: str) -> WorkflowRun:
        """按标识读取运行；不存在时应抛出 ``KeyError``。"""
        raise NotImplementedError

    @abstractmethod
    def delete_run(self, run_id: str, *, delete_orphan_task: bool = True) -> WorkflowRunDeleteResult:
        """删除终态运行，可选清除无其他运行引用的任务；未终态时抛出专用错误。"""
        raise NotImplementedError

    @abstractmethod
    def list_tasks(
        self,
        *,
        status: WorkflowStatus | str | None = None,
        domain: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowStorePage[AgentTask]:
        """按条件分页列出任务；返回排序、复制与并发快照策略由实现定义。"""
        raise NotImplementedError

    @abstractmethod
    def list_runs(
        self,
        *,
        status: WorkflowStatus | str | None = None,
        statuses: Sequence[WorkflowStatus | str] | None = None,
        domain: str | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        lifecycle_phase: str | None = None,
        source: str | None = None,
        sources: Sequence[str] | None = None,
        owner_user_id: str | None = None,
        owner_tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowStorePage[WorkflowRun]:
        """按状态、归属和来源条件分页列出运行；筛选条件共同取交集。"""
        raise NotImplementedError

    @abstractmethod
    def list_non_terminal_runs(self, *, limit: int = 200) -> tuple[WorkflowRun, ...]:
        """返回数量受限、最新优先的未完成运行快照；实现不得返回终态运行。"""
        raise NotImplementedError

    @abstractmethod
    def list_all_runs(self, *, offset: int = 0, limit: int = 200) -> tuple[WorkflowRun, ...]:
        """Return an unscoped page for reconciliation, including terminal runs."""
        raise NotImplementedError

    @abstractmethod
    def find_run_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        """按幂等键查找最近运行；无匹配时返回 ``None``。"""
        raise NotImplementedError
