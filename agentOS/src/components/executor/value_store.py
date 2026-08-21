"""运行期受控数据的引用仓库。

执行图、检查点以及 ``WorkflowRun.executionState`` 只保存引用，不能保存节点输入、
输出正文或 ContextPack 正文。本模块为这些真实数据提供 run 内隔离的读写边界：引用
所属的 runId 与请求读取的 runId 不一致时必须失败，绝不回退到全局查询。

当前内存实现用于融合运行时的服务装配和测试。后续若增加持久化实现，仍必须保留这里
定义的深拷贝与 run 隔离语义，避免调用方通过对象别名篡改已登记的受控数据。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from time import time
from typing import Any, Protocol
from uuid import uuid4

from contracts.execution import NodeExecutionPhase, NodeExecutionRecord


_NODE_PHASE_ORDER = {
    NodeExecutionPhase.PREPARED: 0,
    NodeExecutionPhase.EXECUTED: 1,
    NodeExecutionPhase.AUDITED: 2,
    NodeExecutionPhase.WAITING_REVIEW: 3,
    NodeExecutionPhase.COMMITTED: 4,
    NodeExecutionPhase.FAILED: 4,
    NodeExecutionPhase.CANCELLED: 4,
}
_NODE_TERMINAL_PHASES = {
    NodeExecutionPhase.COMMITTED,
    NodeExecutionPhase.FAILED,
    NodeExecutionPhase.CANCELLED,
}


def _record_payload(record: NodeExecutionRecord) -> dict[str, Any]:
    return record.model_dump(by_alias=True, mode="json")


def _record_from_payload(payload: dict[str, Any], *, fallback: NodeExecutionRecord) -> NodeExecutionRecord:
    if "operationId" not in payload:
        return fallback.model_copy(update={"phase": NodeExecutionPhase.PREPARED})
    return NodeExecutionRecord.model_validate(payload)


def _validate_node_transition(current: NodeExecutionRecord, incoming: NodeExecutionRecord) -> None:
    identity = ("operation_id", "execution_instance_id", "run_id", "step_id", "attempt_id", "loop_path")
    if any(getattr(current, key) != getattr(incoming, key) for key in identity):
        raise ValueError(f"node execution identity cannot change: {incoming.operation_id}")
    if current.phase in _NODE_TERMINAL_PHASES and current != incoming:
        raise ValueError(f"terminal node execution cannot change: {incoming.operation_id}")
    if incoming.phase is NodeExecutionPhase.COMMITTED and not incoming.commit_id:
        raise ValueError("committed node execution requires commitId")


class ExecutionValueAccessError(ValueError):
    """读取不存在或不属于当前 run 的执行值引用时抛出。"""

    def __init__(
        self,
        reference: str,
        owner_run_id: str | None = None,
        requested_run_id: str | None = None,
        message: str | None = None,
    ) -> None:
        """保留归属信息，使调用方能区分越权和引用丢失而不暴露数据正文。"""
        if message is not None:
            resolved_message = message
        elif owner_run_id is None:
            resolved_message = f"execution value reference does not exist: {reference}"
        else:
            resolved_message = (
                f"execution value reference {reference} belongs to run {owner_run_id}, "
                f"not requested run {requested_run_id}"
            )
        super().__init__(resolved_message)
        self.reference = reference
        self.owner_run_id = owner_run_id
        self.requested_run_id = requested_run_id


@dataclass(frozen=True)
class StoredValueRef:
    """不含正文的执行值引用元数据，供延迟清理与审计统计使用。"""

    reference: str
    run_id: str
    step_id: str
    kind: str
    created_at: datetime


class ExecutionValueStore(Protocol):
    """节点执行管线访问受控正文的最小接口。"""

    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        """登记通过输出合同的节点正文，并返回仅供状态保存的引用。"""

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """按当前 run 读取节点正文；跨 run 与缺失引用必须失败。"""

    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        """登记已装配 ContextPack 的 JSON 正文，并返回其引用。"""

    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]:
        """按当前 run 读取 ContextPack 正文；跨 run 与缺失引用必须失败。"""

    def put_graph_patch(self, *, run_id: str, payload: dict[str, Any]) -> str:
        """Persist a graph-patch body outside execution state."""

    def get_graph_patch(self, *, run_id: str, patch_ref: str) -> dict[str, Any]:
        """Dereference a graph patch within its owning run."""

    def assert_reference(self, *, kind: str, run_id: str, step_id: str, reference: str) -> None:
        """确认引用类别、运行和来源步骤均与执行状态声明一致，不读取正文。"""

    def prepare_node_commit(self, *, run_id: str, commit_id: str) -> dict[str, Any]:
        """登记可安全重试的节点准备态，并返回当前不可变记录。"""

    def complete_node_commit(self, *, run_id: str, commit_id: str, payload: dict[str, Any]) -> None:
        """把准备态提交完成为仅含引用和审计元数据的不可变记录。"""

    def get_node_commit(self, *, run_id: str, commit_id: str) -> dict[str, Any] | None:
        """读取同一 run 的节点提交记录；不存在返回 ``None``。"""

    def list_node_commits(self, *, run_id: str) -> tuple[dict[str, Any], ...]:
        """列举当前 run 的引用型节点提交记录，不读取输出或 ContextPack 正文。"""

    def transition_node_execution(self, record: NodeExecutionRecord) -> NodeExecutionRecord:
        """Persist one monotonic node execution phase transition."""

    def list_references(self, *, run_id: str, older_than: datetime) -> tuple[StoredValueRef, ...]:
        """列举早于保留阈值的输出与 ContextPack 元数据，绝不返回正文。"""

    def delete_references(self, *, run_id: str, references: Iterable[str]) -> int:
        """删除当前 run 的输出或 ContextPack 引用并返回实际删除数。"""


class InMemoryExecutionValueStore:
    """面向单进程运行期的引用仓库，严格实现 ``ExecutionValueStore`` 语义。"""

    def __init__(self) -> None:
        """分别保存节点输出与 ContextPack，避免引用类别互相误读。"""
        self._outputs: dict[str, tuple[str, str, dict[str, Any], datetime, str | None]] = {}
        self._context_packs: dict[str, tuple[str, str, dict[str, Any], datetime, str | None]] = {}
        self._graph_patches: dict[str, tuple[str, str, dict[str, Any], datetime, str | None]] = {}
        self._node_commits: dict[str, tuple[str, dict[str, Any]]] = {}
        self._node_executions: dict[str, tuple[str, NodeExecutionRecord]] = {}

    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        """深拷贝已校验输出，防止 Agent 或调用者之后修改原对象。"""
        reference = self._new_reference("output", run_id, step_id)
        self._outputs[reference] = (run_id, step_id, deepcopy(dict(payload)), self._now(), operation_id)
        return reference

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """返回独立副本，确保读取方不能通过别名篡改仓库记录。"""
        return self._get(self._outputs, run_id=run_id, reference=output_ref)

    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        """深拷贝已装配上下文，使 checkpoint 外的正文仍受服务边界保护。"""
        reference = self._new_reference("context", run_id, step_id)
        self._context_packs[reference] = (run_id, step_id, deepcopy(dict(payload)), self._now(), operation_id)
        return reference

    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]:
        """读取 ContextPack 的受控副本，不允许跨 run 访问。"""
        return self._get(self._context_packs, run_id=run_id, reference=context_ref)

    def put_graph_patch(self, *, run_id: str, payload: dict[str, Any]) -> str:
        reference = self._new_reference("graph-patch", run_id, "__graph__")
        self._graph_patches[reference] = (
            run_id,
            "__graph__",
            deepcopy(dict(payload)),
            self._now(),
            None,
        )
        return reference

    def get_graph_patch(self, *, run_id: str, patch_ref: str) -> dict[str, Any]:
        return self._get(self._graph_patches, run_id=run_id, reference=patch_ref)

    def assert_reference(self, *, kind: str, run_id: str, step_id: str, reference: str) -> None:
        """在不返回正文的前提下验证引用的类型、运行与产生步骤。"""
        records = self._records_for_kind(kind)
        self._assert(records, run_id=run_id, step_id=step_id, reference=reference)

    def prepare_node_commit(self, *, run_id: str, commit_id: str) -> dict[str, Any]:
        """创建或复用准备态；该状态表示可携带同一 idempotency key 安全重试。"""
        current = self._node_commits.get(commit_id)
        if current is None:
            payload = {"commitId": commit_id, "stage": "prepared"}
            self._node_commits[commit_id] = (run_id, payload)
            return deepcopy(payload)
        owner_run_id, current_payload = current
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(commit_id, owner_run_id, run_id)
        return deepcopy(current_payload)

    def complete_node_commit(self, *, run_id: str, commit_id: str, payload: dict[str, Any]) -> None:
        """将准备态升级为完成态；重复完成只接受完全相同的安全结果。"""
        current = self._node_commits.get(commit_id)
        if current is None:
            raise ValueError(f"node commit is not prepared: {commit_id}")
        owner_run_id, current_payload = current
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(commit_id, owner_run_id, run_id)
        committed = {"commitId": commit_id, "stage": "committed", **deepcopy(dict(payload))}
        if current_payload.get("stage") != "committed":
            self._node_commits[commit_id] = (run_id, committed)
            return
        if current_payload != committed:
            raise ValueError(f"node commit already exists with different payload: {commit_id}")

    def get_node_commit(self, *, run_id: str, commit_id: str) -> dict[str, Any] | None:
        """读取不可变提交记录；跨 run 请求按执行值越权处理。"""
        record = self._node_commits.get(commit_id)
        if record is None:
            return None
        owner_run_id, payload = record
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(commit_id, owner_run_id, run_id)
        return deepcopy(payload)

    def list_node_commits(self, *, run_id: str) -> tuple[dict[str, Any], ...]:
        """返回当前 run 的提交载荷副本，供恢复与孤儿保护引用收集使用。"""
        return tuple(
            deepcopy(payload)
            for owner_run_id, payload in self._node_commits.values()
            if owner_run_id == run_id
        )

    def transition_node_execution(self, record: NodeExecutionRecord) -> NodeExecutionRecord:
        current = self._node_executions.get(record.operation_id)
        if current is not None:
            owner_run_id, existing = current
            if owner_run_id != record.run_id:
                raise ExecutionValueAccessError(record.operation_id, owner_run_id, record.run_id)
            _validate_node_transition(existing, record)
            if _NODE_PHASE_ORDER[record.phase] < _NODE_PHASE_ORDER[existing.phase]:
                return existing
            if existing.phase in _NODE_TERMINAL_PHASES:
                return existing
        self._node_executions[record.operation_id] = (record.run_id, record)
        return record

    def list_references(self, *, run_id: str, older_than: datetime) -> tuple[StoredValueRef, ...]:
        """按 run 和保留阈值列出可评估的引用元数据，不暴露任何 JSON 正文。"""
        cutoff = self._require_aware_time(older_than)
        records: list[StoredValueRef] = []
        for kind, values in (
            ("output", self._outputs),
            ("context", self._context_packs),
            ("graph-patch", self._graph_patches),
        ):
            for reference, (owner_run_id, step_id, _payload, created_at, _operation_id) in values.items():
                if owner_run_id == run_id and created_at < cutoff:
                    records.append(
                        StoredValueRef(
                            reference=reference,
                            run_id=owner_run_id,
                            step_id=step_id,
                            kind=kind,
                            created_at=created_at,
                        )
                    )
        return tuple(sorted(records, key=lambda item: item.reference))

    def delete_references(self, *, run_id: str, references: Iterable[str]) -> int:
        """只删除明确传入且属于当前 run 的值，跨 run 引用会保留。"""
        deleted = 0
        for reference in set(references):
            for values in (self._outputs, self._context_packs, self._graph_patches):
                record = values.get(reference)
                if record is not None and record[0] == run_id:
                    del values[reference]
                    deleted += 1
                    break
        return deleted

    @staticmethod
    def _new_reference(kind: str, run_id: str, step_id: str) -> str:
        """生成带有类别、归属 run 与来源步骤的可追溯引用。"""
        return f"{kind}:{run_id}:{step_id}:{uuid4().hex}"

    def _get(
        self,
        records: Mapping[str, tuple[str, str, dict[str, Any], datetime, str | None]],
        *,
        run_id: str,
        reference: str,
    ) -> dict[str, Any]:
        """统一执行存在性、run 归属校验及防御性复制。"""
        record = records.get(reference)
        if record is None:
            raise ExecutionValueAccessError(reference)
        owner_run_id, _owner_step_id, payload, _created_at, operation_id = record
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(reference, owner_run_id, run_id)
        self._assert_committed_operation(run_id=run_id, operation_id=operation_id, reference=reference)
        return deepcopy(payload)

    def _records_for_kind(self, kind: str) -> Mapping[str, tuple[str, str, dict[str, Any], datetime, str | None]]:
        if kind == "output":
            return self._outputs
        if kind == "context":
            return self._context_packs
        if kind == "graph-patch":
            return self._graph_patches
        raise ValueError(f"unsupported execution reference kind: {kind}")

    def _assert(
        self,
        records: Mapping[str, tuple[str, str, dict[str, Any], datetime, str | None]],
        *,
        run_id: str,
        step_id: str,
        reference: str,
    ) -> None:
        record = records.get(reference)
        if record is None:
            raise ExecutionValueAccessError(reference)
        owner_run_id, owner_step_id, _payload, _created_at, operation_id = record
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(reference, owner_run_id, run_id)
        if owner_step_id != step_id:
            raise ExecutionValueAccessError(
                reference,
                message=f"execution value reference {reference} belongs to step {owner_step_id}, not declared step {step_id}",
            )
        self._assert_committed_operation(run_id=run_id, operation_id=operation_id, reference=reference)

    def _assert_committed_operation(
        self, *, run_id: str, operation_id: str | None, reference: str
    ) -> None:
        if operation_id is None:
            return
        commit = self.get_node_commit(run_id=run_id, commit_id=operation_id)
        if commit is None or commit.get("stage") != "committed":
            raise ExecutionValueAccessError(
                reference,
                message=f"execution value reference is not committed: {reference}",
            )

    @staticmethod
    def _now() -> datetime:
        """统一生成带时区的创建时间，避免比较本地时间与 UTC 时间。"""
        return datetime.now(timezone.utc)

    @staticmethod
    def _require_aware_time(value: datetime) -> datetime:
        """拒绝无时区阈值，防止宿主机时区变化改变清理范围。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("older_than must include a timezone")
        return value.astimezone(timezone.utc)


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
                step_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS acg_node_executions (
                operation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                phase TEXT NOT NULL
            )"""
        )
        value_columns = {
            str(row[1]) for row in self._connection.execute("PRAGMA table_info(execution_values)")
        }
        if "step_id" not in value_columns:
            self._connection.execute(
                "ALTER TABLE execution_values ADD COLUMN step_id TEXT NOT NULL DEFAULT ''"
            )
        if "created_at" not in value_columns:
            # 旧版本没有可追溯创建时间。把升级时刻作为年龄起点，先完整保留一个
            # retention 周期，不能因元数据缺失把历史审核或恢复正文立即当作孤儿。
            self._connection.execute("ALTER TABLE execution_values ADD COLUMN created_at REAL")
            self._connection.execute(
                "UPDATE execution_values SET created_at = ? WHERE created_at IS NULL",
                (time(),),
            )
        if "operation_id" not in value_columns:
            self._connection.execute(
                "ALTER TABLE execution_values ADD COLUMN operation_id TEXT"
            )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS acg_node_commits (
                commit_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'prepared'
            )"""
        )
        columns = {
            str(row[1]) for row in self._connection.execute("PRAGMA table_info(acg_node_commits)")
        }
        if "stage" not in columns:
            self._connection.execute(
                "ALTER TABLE acg_node_commits ADD COLUMN stage TEXT NOT NULL DEFAULT 'prepared'"
            )
        self._connection.commit()

    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        """持久化通过输出合同的节点正文，并返回稳定输出引用。"""
        return self._put("output", run_id=run_id, step_id=step_id, payload=payload, operation_id=operation_id)

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """按 run 隔离读取输出正文，禁止跨运行回退。"""
        return self._get("output", run_id=run_id, reference=output_ref)

    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        """持久化 ContextPack 正文，仅将其引用交给执行状态与检查点。"""
        return self._put("context", run_id=run_id, step_id=step_id, payload=payload, operation_id=operation_id)

    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]:
        """按 run 隔离读取 ContextPack 正文，禁止跨运行回退。"""
        return self._get("context", run_id=run_id, reference=context_ref)

    def put_graph_patch(self, *, run_id: str, payload: dict[str, Any]) -> str:
        return self._put("graph-patch", run_id=run_id, step_id="__graph__", payload=payload)

    def get_graph_patch(self, *, run_id: str, patch_ref: str) -> dict[str, Any]:
        return self._get("graph-patch", run_id=run_id, reference=patch_ref)

    def assert_reference(self, *, kind: str, run_id: str, step_id: str, reference: str) -> None:
        """验证持久引用的类型、运行和产生步骤，不读取或返回其正文。"""
        row = self._connection.execute(
            "SELECT run_id, step_id, kind, operation_id FROM execution_values WHERE reference = ?",
            (reference,),
        ).fetchone()
        if row is None:
            raise ExecutionValueAccessError(reference)
        owner_run_id, owner_step_id, actual_kind = (str(value) for value in row[:3])
        operation_id = str(row[3]) if row[3] is not None else None
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(reference, owner_run_id, run_id)
        if actual_kind != kind:
            raise ExecutionValueAccessError(reference)
        if owner_step_id != step_id:
            raise ExecutionValueAccessError(
                reference,
                message=f"execution value reference {reference} belongs to step {owner_step_id}, not declared step {step_id}",
            )
        self._assert_committed_operation(run_id=run_id, operation_id=operation_id, reference=reference)

    def prepare_node_commit(self, *, run_id: str, commit_id: str) -> dict[str, Any]:
        """在 SQLite 中原子创建或读取准备态，进程重启后仍使用同一提交标识。"""
        prepared = {"commitId": commit_id, "stage": "prepared"}
        encoded = json.dumps(prepared, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT run_id, payload_json FROM acg_node_commits WHERE commit_id = ?",
                (commit_id,),
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO acg_node_commits(commit_id, run_id, payload_json, stage) VALUES (?, ?, ?, 'prepared')",
                    (commit_id, run_id, encoded),
                )
                result = prepared
            else:
                owner_run_id, existing = str(row[0]), str(row[1])
                if owner_run_id != run_id:
                    raise ExecutionValueAccessError(commit_id, owner_run_id, run_id)
                result = json.loads(existing)
            self._connection.commit()
            return deepcopy(result)
        except Exception:
            self._connection.rollback()
            raise

    def complete_node_commit(self, *, run_id: str, commit_id: str, payload: dict[str, Any]) -> None:
        """仅允许将已准备的提交一次性升级为完成态，防止重放改写结果。"""
        committed = {"commitId": commit_id, "stage": "committed", **deepcopy(dict(payload))}
        encoded = json.dumps(committed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT run_id, payload_json, stage FROM acg_node_commits WHERE commit_id = ?",
                (commit_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"node commit is not prepared: {commit_id}")
            owner_run_id, existing, stage = str(row[0]), str(row[1]), str(row[2])
            if owner_run_id != run_id:
                raise ExecutionValueAccessError(commit_id, owner_run_id, run_id)
            if stage != "committed":
                self._connection.execute(
                    "UPDATE acg_node_commits SET payload_json = ?, stage = 'committed' WHERE commit_id = ?",
                    (encoded, commit_id),
                )
            elif existing != encoded:
                raise ValueError(f"node commit already exists with different payload: {commit_id}")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def get_node_commit(self, *, run_id: str, commit_id: str) -> dict[str, Any] | None:
        """读取 run 内提交记录；提交载荷仅含引用和审计元数据。"""
        row = self._connection.execute(
            "SELECT run_id, payload_json FROM acg_node_commits WHERE commit_id = ?",
            (commit_id,),
        ).fetchone()
        if row is None:
            return None
        owner_run_id, payload_json = str(row[0]), str(row[1])
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(commit_id, owner_run_id, run_id)
        return deepcopy(json.loads(payload_json))

    def list_node_commits(self, *, run_id: str) -> tuple[dict[str, Any], ...]:
        """按 run 列举提交的安全载荷，数据库查询不包含执行正文表。"""
        rows = self._connection.execute(
            "SELECT payload_json FROM acg_node_commits WHERE run_id = ? ORDER BY commit_id",
            (run_id,),
        ).fetchall()
        return tuple(deepcopy(json.loads(str(row[0]))) for row in rows)

    def transition_node_execution(self, record: NodeExecutionRecord) -> NodeExecutionRecord:
        encoded = json.dumps(_record_payload(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT run_id, payload_json FROM acg_node_executions WHERE operation_id = ?",
                (record.operation_id,),
            ).fetchone()
            if row is not None:
                owner_run_id, payload_json = str(row[0]), str(row[1])
                if owner_run_id != record.run_id:
                    raise ExecutionValueAccessError(record.operation_id, owner_run_id, record.run_id)
                existing = _record_from_payload(json.loads(payload_json), fallback=record)
                _validate_node_transition(existing, record)
                if _NODE_PHASE_ORDER[record.phase] < _NODE_PHASE_ORDER[existing.phase]:
                    self._connection.commit()
                    return existing
                if existing.phase in _NODE_TERMINAL_PHASES:
                    self._connection.commit()
                    return existing
                self._connection.execute(
                    "UPDATE acg_node_executions SET payload_json = ?, phase = ? WHERE operation_id = ?",
                    (encoded, record.phase.value, record.operation_id),
                )
            else:
                self._connection.execute(
                    "INSERT INTO acg_node_executions(operation_id, run_id, payload_json, phase) VALUES (?, ?, ?, ?)",
                    (record.operation_id, record.run_id, encoded, record.phase.value),
                )
            self._connection.commit()
            return record
        except Exception:
            self._connection.rollback()
            raise

    def list_references(self, *, run_id: str, older_than: datetime) -> tuple[StoredValueRef, ...]:
        """只读取候选值的元数据；查询始终带 runId 条件避免跨运行扫描。"""
        if older_than.tzinfo is None or older_than.utcoffset() is None:
            raise ValueError("older_than must include a timezone")
        rows = self._connection.execute(
            """SELECT reference, run_id, step_id, kind, created_at
               FROM execution_values
               WHERE run_id = ? AND created_at < ?
               ORDER BY reference""",
            (run_id, older_than.astimezone(timezone.utc).timestamp()),
        ).fetchall()
        return tuple(
            StoredValueRef(
                reference=str(row[0]),
                run_id=str(row[1]),
                step_id=str(row[2]),
                kind=str(row[3]),
                created_at=datetime.fromtimestamp(float(row[4]), tz=timezone.utc),
            )
            for row in rows
        )

    def delete_references(self, *, run_id: str, references: Iterable[str]) -> int:
        """在 SQLite 事务中按 run 约束删除引用，不匹配归属的项不会受影响。"""
        unique = tuple(set(references))
        if not unique:
            return 0
        deleted = 0
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            for reference in unique:
                cursor = self._connection.execute(
                    "DELETE FROM execution_values WHERE reference = ? AND run_id = ?",
                    (reference, run_id),
                )
                deleted += max(0, int(cursor.rowcount))
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return deleted

    def close(self) -> None:
        """关闭当前 SQLite 连接；运行时退出时由装配层负责调用。"""
        self._connection.close()

    def _put(self, kind: str, *, run_id: str, step_id: str, payload: dict[str, Any], operation_id: str | None = None) -> str:
        reference = self._new_reference(kind, run_id, step_id)
        encoded = json.dumps(deepcopy(dict(payload)), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        self._connection.execute(
            """INSERT INTO execution_values
               (reference, run_id, step_id, kind, payload_json, created_at, operation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (reference, run_id, step_id, kind, encoded, time(), operation_id),
        )
        self._connection.commit()
        return reference

    def _get(self, kind: str, *, run_id: str, reference: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT run_id, kind, payload_json, operation_id FROM execution_values WHERE reference = ?",
            (reference,),
        ).fetchone()
        if row is None:
            raise ExecutionValueAccessError(reference)
        owner_run_id, actual_kind, payload_json, operation_id = row
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(reference, str(owner_run_id), run_id)
        if actual_kind != kind:
            raise ExecutionValueAccessError(reference)
        self._assert_committed_operation(
            run_id=run_id,
            operation_id=str(operation_id) if operation_id is not None else None,
            reference=reference,
        )
        payload = json.loads(payload_json)
        return deepcopy(payload)

    def _assert_committed_operation(
        self, *, run_id: str, operation_id: str | None, reference: str
    ) -> None:
        if operation_id is None:
            return
        row = self._connection.execute(
            "SELECT run_id, stage FROM acg_node_commits WHERE commit_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None or str(row[0]) != run_id or str(row[1]) != "committed":
            raise ExecutionValueAccessError(
                reference,
                message=f"execution value reference is not committed: {reference}",
            )

    @staticmethod
    def _new_reference(kind: str, run_id: str, step_id: str) -> str:
        return f"{kind}:{run_id}:{step_id}:{uuid4().hex}"


__all__ = [
    "ExecutionValueAccessError",
    "ExecutionValueStore",
    "InMemoryExecutionValueStore",
    "SQLiteExecutionValueStore",
    "StoredValueRef",
]
