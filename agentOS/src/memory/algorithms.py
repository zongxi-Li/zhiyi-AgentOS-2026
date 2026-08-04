"""记忆排序的纯函数。"""

from contracts.memory import MemoryRecord


def rerank_memories(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """按重要度降序、标识升序稳定排序，便于结果复现。"""
    return sorted(records, key=lambda item: (-item.importance, item.memory_id))
