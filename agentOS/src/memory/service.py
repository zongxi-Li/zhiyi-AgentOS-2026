"""记忆部件的公共 Facade。"""

from contracts.memory import MemoryPolicy, MemoryQuery, MemoryRecord

from .admission import admitted
from .algorithms import rerank_memories
from .retrieval import retrieve
from .store import MemoryStore


class MemoryService:
    """提供经准入检查的写入和稳定排序的本地读取。"""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or MemoryStore()

    def remember(self, record: MemoryRecord, policy: MemoryPolicy | None = None) -> bool:
        """符合策略时写入并返回真，否则不修改存储。"""
        if not admitted(record, policy):
            return False
        self._store.put(record)
        return True

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        """执行本地元数据检索和稳定重排。"""
        return rerank_memories(retrieve(self._store.values(), query))
