"""可替换的进程内记忆仓库。"""

import json
from pathlib import Path
import sqlite3

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


class SQLiteMemoryStore:
    """面向审核续跑的 SQLite 记忆仓库。

    运行期 MemoryService 仍是唯一读写入口；本类只负责把已经通过准入的
    ``MemoryRecord`` 持久化。恢复后的节点再次按 runId 召回时，因此不会因进程重启
    丢失已完成步骤的情节记忆，也不会绕过 scope 与过期过滤。
    """

    def __init__(self, *, db_path: str | Path) -> None:
        """打开独立记忆文件并创建 JSON 记录表。"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS execution_memory (
                memory_id TEXT PRIMARY KEY,
                record_json TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    def put(self, record: MemoryRecord) -> None:
        """按记忆标识覆盖保存合同 JSON，不保存运行时对象。"""
        payload = json.dumps(record.model_dump(by_alias=True, mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._connection.execute(
            "INSERT OR REPLACE INTO execution_memory(memory_id, record_json) VALUES (?, ?)",
            (record.memory_id, payload),
        )
        self._connection.commit()

    def values(self) -> list[MemoryRecord]:
        """读取全部合同记录，由 MemoryService 继续执行范围、过期与排序控制。"""
        rows = self._connection.execute("SELECT record_json FROM execution_memory ORDER BY rowid").fetchall()
        return [MemoryRecord.model_validate(json.loads(row[0])) for row in rows]

    def close(self) -> None:
        """关闭当前数据库连接。"""
        self._connection.close()
