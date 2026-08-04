"""可替换的进程内记忆仓库。"""

from contracts.memory import MemoryRecord


class MemoryStore:
    """存放合同对象的最小仓库，不包含向量数据库依赖。"""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def put(self, record: MemoryRecord) -> None:
        self._records[record.memory_id] = record

    def values(self) -> list[MemoryRecord]:
        return list(self._records.values())

    # TODO: 接入 SQLite/向量数据库适配器，并实现索引、事务和加密配置。
