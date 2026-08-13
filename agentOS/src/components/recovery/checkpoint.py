"""AgentOS 的 SQLite 执行检查点存储。

每个 ``runId`` 映射为 LangGraph 语义中的 thread ID，但数据库表、命令和异常均使用
AgentOS 命名。检查点文件独立于 WorkflowStore，由 ``AGENTOS_LANGGRAPH_CHECKPOINT_DB``
指定，默认写入 ``data/langgraph_checkpoints.sqlite3``，因此可在进程重启后读取。

存储内容只能是 ``ACGExecutionState`` 等引用型 JSON；不得把完整 slot 输入输出、
ContextPack 正文或回调对象放入其中。

第三方来源：LangGraph 1.2.10，commit d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086；
来源模块 ``libs/checkpoint-sqlite/langgraph/checkpoint/sqlite``。完整 MIT 许可证见
``docs/THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExecutionInterrupt(Exception):
    """审核点暂停执行时抛出的 AgentOS 中断信号。

    ``payload`` 只携带审核 UI 和恢复所需的引用信息；runtime 捕获后应先保存 checkpoint，
    再将 run 投影为等待审核状态。
    """

    def __init__(self, prompt: str, payload: dict[str, Any] | None = None) -> None:
        self.prompt = prompt
        self.payload = payload or {}
        super().__init__(prompt)


class ExecutionResumeCommand(BaseModel):
    """AgentOS 对外恢复命令，不暴露 LangGraph ``Command`` 类型。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    run_id: str = Field(alias="runId")
    payload: dict[str, Any] = Field(default_factory=dict)


class ACGCheckpointStore:
    """独立 SQLite 文件中的持久化检查点仓库。

    主键由 ``thread_id(runId) + checkpoint_id`` 组成，保证不同运行间完全隔离；调用方
    负责同一 run 的更高层互斥和 checkpoint 与 WorkflowStore 的事务编排。
    """

    def __init__(self, *, db_path: str | Path | None = None) -> None:
        """解析配置路径、创建父目录并初始化检查点表。"""
        configured = os.getenv("AGENTOS_LANGGRAPH_CHECKPOINT_DB", "").strip()
        self.db_path = Path(db_path or configured or "data/langgraph_checkpoints.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.execute("""CREATE TABLE IF NOT EXISTS acg_execution_checkpoints (
            thread_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL, state_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, checkpoint_id))""")
        self._connection.commit()

    def save(self, *, run_id: str, checkpoint_id: str | None = None, state: dict[str, Any]) -> str:
        """保存一个 JSON 状态快照；未指定标识时生成新的检查点标识。"""
        identifier = checkpoint_id or f"acgckpt_{uuid4().hex}"
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        self._connection.execute("INSERT OR REPLACE INTO acg_execution_checkpoints(thread_id, checkpoint_id, state_json) VALUES (?, ?, ?)", (run_id, identifier, payload))
        self._connection.commit()
        return identifier

    def load(self, *, run_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """读取指定 run 的指定检查点；不存在返回 ``None``，不跨 run 回退查询。"""
        row = self._connection.execute("SELECT state_json FROM acg_execution_checkpoints WHERE thread_id = ? AND checkpoint_id = ?", (run_id, checkpoint_id)).fetchone()
        return json.loads(row[0]) if row else None

    def load_latest(self, *, run_id: str) -> tuple[str, dict[str, Any]]:
        """读取一个 run/thread 最近写入的检查点，用于进程重启后的续跑。"""
        row = self._connection.execute(
            "SELECT checkpoint_id, state_json FROM acg_execution_checkpoints WHERE thread_id = ? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no checkpoint found for run {run_id}")
        return str(row[0]), json.loads(row[1])

    def close(self) -> None:
        """关闭当前 SQLite 连接；仓库实例关闭后不得继续读写。"""
        self._connection.close()


__all__ = ["ACGCheckpointStore", "ExecutionInterrupt", "ExecutionResumeCommand"]
