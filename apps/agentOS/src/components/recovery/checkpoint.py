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


class CheckpointConflictError(RuntimeError):
    """检查点版本冲突，表示调用方正在使用已经过期的状态快照。"""


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
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, checkpoint_id))""")
        columns = {
            str(row[1])
            for row in self._connection.execute("PRAGMA table_info(acg_execution_checkpoints)")
        }
        if "version" not in columns:
            self._connection.execute(
                "ALTER TABLE acg_execution_checkpoints ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
            )
        self._connection.commit()

    def save(
        self,
        *,
        run_id: str,
        checkpoint_id: str | None = None,
        state: dict[str, Any],
        expected_version: int | None = None,
    ) -> str:
        """保存 JSON 状态快照，并按运行维度执行可选的版本 CAS。"""
        identifier = checkpoint_id or f"acgckpt_{uuid4().hex}"
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        try:
            # 写锁覆盖“读取当前版本→比较→写入”整个过程，保证多个 Runtime 进程
            # 同时恢复同一 run 时，旧状态不能越过 CAS 检查覆盖新状态。
            self._connection.execute("BEGIN IMMEDIATE")
            current_row = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM acg_execution_checkpoints WHERE thread_id = ?",
                (run_id,),
            ).fetchone()
            current_version = int(current_row[0] or 0)
            if expected_version is not None and expected_version != current_version:
                raise CheckpointConflictError(
                    f"checkpoint version {expected_version} does not match current version {current_version}"
                )
            existing = self._connection.execute(
                "SELECT state_json FROM acg_execution_checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
                (run_id, identifier),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != payload:
                    raise CheckpointConflictError(
                        f"checkpoint id already exists with different state: {identifier}"
                    )
                self._connection.commit()
                return identifier
            next_version = current_version + 1
            self._connection.execute(
                "INSERT OR REPLACE INTO acg_execution_checkpoints(thread_id, checkpoint_id, state_json, version) VALUES (?, ?, ?, ?)",
                (run_id, identifier, payload, next_version),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return identifier

    def load(self, *, run_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """读取指定 run 的指定检查点；不存在返回 ``None``，不跨 run 回退查询。"""
        row = self._connection.execute("SELECT state_json FROM acg_execution_checkpoints WHERE thread_id = ? AND checkpoint_id = ?", (run_id, checkpoint_id)).fetchone()
        return json.loads(row[0]) if row else None

    def load_latest(self, *, run_id: str) -> tuple[str, dict[str, Any]]:
        """读取一个 run/thread 最近写入的检查点，用于进程重启后的续跑。"""
        row = self._connection.execute(
            "SELECT checkpoint_id, state_json FROM acg_execution_checkpoints WHERE thread_id = ? ORDER BY version DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no checkpoint found for run {run_id}")
        return str(row[0]), json.loads(row[1])

    def list_states(self, *, run_id: str) -> tuple[dict[str, Any], ...]:
        """返回当前 run 的全部引用型检查点状态，供孤儿保护扫描使用。

        结果按版本排序，不读取其它运行的数据。调用方只能从中提取已知引用字段，
        不得将状态正文扩散到日志、Trace 或未受控的应用内存。
        """
        rows = self._connection.execute(
            """SELECT state_json FROM acg_execution_checkpoints
               WHERE thread_id = ? ORDER BY version""",
            (run_id,),
        ).fetchall()
        return tuple(json.loads(str(row[0])) for row in rows)

    def version(self, *, run_id: str, checkpoint_id: str) -> int:
        """读取检查点版本；不存在时明确报告缺失。"""
        row = self._connection.execute(
            "SELECT version FROM acg_execution_checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
            (run_id, checkpoint_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"checkpoint does not exist for run {run_id}: {checkpoint_id}")
        return int(row[0])

    def latest_version(self, *, run_id: str) -> int:
        """读取某个运行当前最新检查点版本；尚无检查点时返回零。"""
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM acg_execution_checkpoints WHERE thread_id = ?",
            (run_id,),
        ).fetchone()
        return int(row[0] or 0)

    def close(self) -> None:
        """关闭当前 SQLite 连接；仓库实例关闭后不得继续读写。"""
        self._connection.close()


__all__ = ["ACGCheckpointStore", "CheckpointConflictError", "ExecutionInterrupt", "ExecutionResumeCommand"]
