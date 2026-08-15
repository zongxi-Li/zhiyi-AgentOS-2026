"""记忆排序的纯函数。"""

from contracts.memory import MemoryRecord


def rerank_memories(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """按重要度降序、标识升序返回稳定的记忆排序副本。

    输入列表不会被原地改写；相同重要度通过 ``memory_id`` 打破平局，便于重放。
    对 n 条记录排序的时间复杂度 O(n log n)、额外空间 O(n)。
    """
    return sorted(records, key=lambda item: (-item.importance, item.memory_id))
