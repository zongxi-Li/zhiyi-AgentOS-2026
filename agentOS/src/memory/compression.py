"""记忆压缩的保守实现。"""

from contracts.memory import MemoryRecord


def compact_record(record: MemoryRecord) -> dict[str, object]:
    """返回可审计的最小摘要，不丢弃原始仓库中的记录。"""
    return {"memoryId": record.memory_id, "type": record.memory_type.value, "importance": record.importance}
