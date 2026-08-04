"""可替换的进程内记忆仓库。"""

from contracts.memory import MemoryRecord


class MemoryStore:
    """以记忆标识保存合同对象的最小进程内仓库。

    同一标识的新记录覆盖旧记录；实现不复制对象、不持久化、没有锁或向量索引，
    因此调用方负责对象可变性及跨线程/进程并发边界。
    """

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def put(self, record: MemoryRecord) -> None:
        """按 ``record.memory_id`` 保存或覆盖一条记忆记录。

        记录对象以原引用存储，之后对其的修改会被后续读取看见；方法不验证策略、
        过期或容量。字典写入平均时间和额外空间复杂度均为 O(1)。
        """
        self._records[record.memory_id] = record

    def values(self) -> list[MemoryRecord]:
        """返回当前记录引用构成的新列表。

        修改返回列表不会改变仓库，但其中记录对象与仓库共享；迭代顺序遵循字典
        插入顺序。时间与额外空间复杂度均为 O(n)。
        """
        return list(self._records.values())

    # TODO: 接入 SQLite/向量数据库适配器，并实现索引、事务和加密配置。
