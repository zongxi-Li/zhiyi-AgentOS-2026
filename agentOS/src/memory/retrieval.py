"""本地记忆检索。"""

from contracts.memory import MemoryQuery, MemoryRecord


def retrieve(records: list[MemoryRecord], query: MemoryQuery) -> list[MemoryRecord]:
    """按范围、类型、标签做确定性过滤，不伪装为语义向量检索。"""
    selected = [record for record in records if (not query.memory_types or record.memory_type in query.memory_types) and (query.scope is None or record.scope == query.scope) and set(query.tags).issubset(record.tags)]
    return selected[:query.limit]


# TODO: 接入向量检索适配器后，根据嵌入相似度和权限过滤执行召回。
