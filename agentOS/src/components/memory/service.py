"""记忆部件的公共 Facade。"""

from contracts.memory import MemoryPolicy, MemoryQuery, MemoryRecord

from .admission import admitted
from .algorithms import rerank_memories
from .retrieval import retrieve
from .models import WorkingMemory
from .store import MemoryStore


class MemoryService:
    """提供经策略准入的内存写入、确定性检索和工作记忆构造。

    默认使用进程内 ``MemoryStore``，不提供事务、持久化或并发锁；调用者若需
    跨线程/进程一致性，应注入具备相应语义的存储实现。
    """

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or MemoryStore()

    def remember(self, record: MemoryRecord, policy: MemoryPolicy | None = None) -> bool:
        """在 ``record`` 符合可选策略时写入并返回 ``True``。

        拒绝时返回 ``False`` 且不修改存储；接受时覆盖规则由底层存储定义。该
        方法不检查容量或过期，存储错误直接上抛，复杂度由注入存储决定。
        """
        if not admitted(record, policy):
            return False
        self._store.put(record)
        return True

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        """执行本地元数据过滤后按重要度稳定重排并返回结果副本。

        检索不使用向量模型或外部索引，输入查询不会被修改；复杂度包含线性过滤
        和排序，即 O(n log n)，底层存储读取异常会直接上抛。
        """
        return rerank_memories(retrieve(self._store.values(), query))

    def working_from_run(self, run: object) -> WorkingMemory:
        """从运行投影创建一份仅含已完成观察的 ``WorkingMemory``。

        返回新对象，不改变运行或访问旧 core；步骤解释规则由
        :meth:`WorkingMemory.from_run` 定义，处理复杂度随步骤数线性增长。
        """
        return WorkingMemory.from_run(run)
