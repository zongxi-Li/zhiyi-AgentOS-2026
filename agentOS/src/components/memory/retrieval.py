"""本地记忆检索。"""

from contracts.memory import MemoryQuery, MemoryRecord


def retrieve(records: list[MemoryRecord], query: MemoryQuery) -> list[MemoryRecord]:
    """按类型、范围和标签对本地记录作确定性过滤并限制数量。

    返回保留输入相对顺序的前 ``query.limit`` 条，未做向量相似度、权限或过期
    处理；这些边界由外部检索适配器负责。时间 O(n)，返回列表额外空间 O(k)。
    """
    selected = [record for record in records if (not query.memory_types or record.memory_type in query.memory_types) and (query.scope is None or record.scope == query.scope) and set(query.tags).issubset(record.tags)]
    return selected[:query.limit]


# TODO: 接入向量检索适配器后，根据嵌入相似度和权限过滤执行召回。
# TODO(可迁移): 可通过 Adapter 借鉴 Mem0 的记忆合并/向量召回及 Haystack 的
# DocumentStore/Retriever 模式；MemoryService 必须保持唯一读写入口，外部存储不得绕过
# 准入、权限、审计或生命周期。代码级复用前须复核 Apache-2.0 的 LICENSE、NOTICE 与子依赖。
