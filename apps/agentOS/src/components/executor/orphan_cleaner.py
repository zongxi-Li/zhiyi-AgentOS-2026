"""执行正文孤儿的延迟清理服务。

该服务只清理无主输出和 ContextPack 的受控值引用。调用方从运行 State、checkpoint
和待审核记忆意图收集保护引用；本服务补充执行 WAL 和不可变操作记录的所有权。
审计决定、血缘、正式记忆、提交记录与 checkpoint 都不是本服务的删除目标。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .value_store import ExecutionValueStore


@dataclass(frozen=True)
class OrphanCleanupStats:
    """一次无正文清理的安全统计，可投影到 Trace 审计事件。"""

    run_id: str
    scanned: int
    protected: int
    deleted: int
    older_than: datetime


class ExecutionOrphanCleaner:
    """根据调用方给定的保护集合，删除当前 run 中已过期的无主执行正文。"""

    def __init__(self, *, value_store: ExecutionValueStore) -> None:
        self.value_store = value_store

    def clean(
        self,
        *,
        run_id: str,
        protected_refs: set[str],
        older_than: datetime,
    ) -> OrphanCleanupStats:
        """扫描当前 run 的到期记录，删除未保护项并返回计数，不读取正文。"""
        # Failed/prepared inputs are owned by the execution WAL even when no
        # result reached graph State or a committed node receipt.
        protected_refs = set(protected_refs)
        for execution in self.value_store.list_node_executions(run_id=run_id):
            protected_refs.update(reference for kind in ("context", "memoryInput")
                                  if (reference := execution.artifact_refs.get(kind)))
        # Tool values are immutable operation WAL, not unpublished node outputs.
        # Receipts, frozen planning reads and compacted views remain owned by
        # their Run even after the graph frontier or active session advances.
        protected_refs.update(item.reference for item in self.value_store.list_tool_references(run_id=run_id))
        candidates = self.value_store.list_references(run_id=run_id, older_than=older_than)
        protected = tuple(item for item in candidates if item.reference in protected_refs)
        delete_refs = tuple(item.reference for item in candidates if item.reference not in protected_refs)
        deleted = self.value_store.delete_references(run_id=run_id, references=delete_refs)
        return OrphanCleanupStats(
            run_id=run_id,
            scanned=len(candidates),
            protected=len(protected),
            deleted=deleted,
            older_than=older_than,
        )


__all__ = ["ExecutionOrphanCleaner", "OrphanCleanupStats"]
