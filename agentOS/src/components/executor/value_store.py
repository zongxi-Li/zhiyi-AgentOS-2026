"""运行期受控数据的引用仓库。

执行图、检查点以及 ``WorkflowRun.executionState`` 只保存引用，不能保存节点输入、
输出正文或 ContextPack 正文。本模块为这些真实数据提供 run 内隔离的读写边界：引用
所属的 runId 与请求读取的 runId 不一致时必须失败，绝不回退到全局查询。

当前内存实现用于融合运行时的服务装配和测试。后续若增加持久化实现，仍必须保留这里
定义的深拷贝与 run 隔离语义，避免调用方通过对象别名篡改已登记的受控数据。
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Protocol
from uuid import uuid4


class ExecutionValueAccessError(ValueError):
    """读取不存在或不属于当前 run 的执行值引用时抛出。"""

    def __init__(
        self,
        reference: str,
        owner_run_id: str | None = None,
        requested_run_id: str | None = None,
    ) -> None:
        """保留归属信息，使调用方能区分越权和引用丢失而不暴露数据正文。"""
        if owner_run_id is None:
            message = f"execution value reference does not exist: {reference}"
        else:
            message = (
                f"execution value reference {reference} belongs to run {owner_run_id}, "
                f"not requested run {requested_run_id}"
            )
        super().__init__(message)
        self.reference = reference
        self.owner_run_id = owner_run_id
        self.requested_run_id = requested_run_id


class ExecutionValueStore(Protocol):
    """节点执行管线访问受控正文的最小接口。"""

    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        """登记通过输出合同的节点正文，并返回仅供状态保存的引用。"""

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """按当前 run 读取节点正文；跨 run 与缺失引用必须失败。"""

    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        """登记已装配 ContextPack 的 JSON 正文，并返回其引用。"""

    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]:
        """按当前 run 读取 ContextPack 正文；跨 run 与缺失引用必须失败。"""


class InMemoryExecutionValueStore:
    """面向单进程运行期的引用仓库，严格实现 ``ExecutionValueStore`` 语义。"""

    def __init__(self) -> None:
        """分别保存节点输出与 ContextPack，避免引用类别互相误读。"""
        self._outputs: dict[str, tuple[str, dict[str, Any]]] = {}
        self._context_packs: dict[str, tuple[str, dict[str, Any]]] = {}

    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        """深拷贝已校验输出，防止 Agent 或调用者之后修改原对象。"""
        reference = self._new_reference("output", run_id, step_id)
        self._outputs[reference] = (run_id, deepcopy(dict(payload)))
        return reference

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """返回独立副本，确保读取方不能通过别名篡改仓库记录。"""
        return self._get(self._outputs, run_id=run_id, reference=output_ref)

    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        """深拷贝已装配上下文，使 checkpoint 外的正文仍受服务边界保护。"""
        reference = self._new_reference("context", run_id, step_id)
        self._context_packs[reference] = (run_id, deepcopy(dict(payload)))
        return reference

    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]:
        """读取 ContextPack 的受控副本，不允许跨 run 访问。"""
        return self._get(self._context_packs, run_id=run_id, reference=context_ref)

    @staticmethod
    def _new_reference(kind: str, run_id: str, step_id: str) -> str:
        """生成带有类别、归属 run 与来源步骤的可追溯引用。"""
        return f"{kind}:{run_id}:{step_id}:{uuid4().hex}"

    @staticmethod
    def _get(
        records: Mapping[str, tuple[str, dict[str, Any]]],
        *,
        run_id: str,
        reference: str,
    ) -> dict[str, Any]:
        """统一执行存在性、run 归属校验及防御性复制。"""
        record = records.get(reference)
        if record is None:
            raise ExecutionValueAccessError(reference)
        owner_run_id, payload = record
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(reference, owner_run_id, run_id)
        return deepcopy(payload)


class SQLiteExecutionValueStore:
    """用于可恢复运行的 SQLite 引用仓库。

    检查点只存 ``outputRef`` 和 ``contextRef``，正文由本仓库独立保存。因此进程重启后
    Runtime 能够重新解析审核前的上游输入，同时仍按 ``run_id`` 做第一层隔离。本文件
    与 checkpoint 使用独立数据库，避免工作流元数据、检查点和正文互相耦合。
    """

    def __init__(self, *, db_path: str | Path) -> None:
        """打开独立数据文件并建立引用记录表，不接管 WorkflowStore 连接。"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS execution_values (
                reference TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        """持久化通过输出合同的节点正文，并返回稳定输出引用。"""
        return self._put("output", run_id=run_id, step_id=step_id, payload=payload)

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """按 run 隔离读取输出正文，禁止跨运行回退。"""
        return self._get("output", run_id=run_id, reference=output_ref)

    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        """持久化 ContextPack 正文，仅将其引用交给执行状态与检查点。"""
        return self._put("context", run_id=run_id, step_id=step_id, payload=payload)

    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]:
        """按 run 隔离读取 ContextPack 正文，禁止跨运行回退。"""
        return self._get("context", run_id=run_id, reference=context_ref)

    def close(self) -> None:
        """关闭当前 SQLite 连接；运行时退出时由装配层负责调用。"""
        self._connection.close()

    def _put(self, kind: str, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        reference = self._new_reference(kind, run_id, step_id)
        encoded = json.dumps(deepcopy(dict(payload)), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        self._connection.execute(
            "INSERT INTO execution_values(reference, run_id, kind, payload_json) VALUES (?, ?, ?, ?)",
            (reference, run_id, kind, encoded),
        )
        self._connection.commit()
        return reference

    def _get(self, kind: str, *, run_id: str, reference: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT run_id, kind, payload_json FROM execution_values WHERE reference = ?",
            (reference,),
        ).fetchone()
        if row is None:
            raise ExecutionValueAccessError(reference)
        owner_run_id, actual_kind, payload_json = row
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(reference, str(owner_run_id), run_id)
        if actual_kind != kind:
            raise ExecutionValueAccessError(reference)
        payload = json.loads(payload_json)
        return deepcopy(payload)

    @staticmethod
    def _new_reference(kind: str, run_id: str, step_id: str) -> str:
        return f"{kind}:{run_id}:{step_id}:{uuid4().hex}"


__all__ = [
    "ExecutionValueAccessError",
    "ExecutionValueStore",
    "InMemoryExecutionValueStore",
    "SQLiteExecutionValueStore",
]
