"""记忆压缩的保守实现。"""

from contracts.memory import MemoryRecord


def compact_record(record: MemoryRecord) -> dict[str, object]:
    """提取 ``record`` 的标识、类型和重要度作为可审计最小摘要。

    返回新字典而不修改原记录，也不删除原始内容；摘要不是语义压缩或脱敏结果。
    字段数固定，因此时间与空间复杂度均为 O(1)。
    """
    return {"memoryId": record.memory_id, "type": record.memory_type.value, "importance": record.importance}
