"""审计决定的独立持久化仓库。"""

from __future__ import annotations

from collections.abc import Set
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Protocol

from contracts.governance import PolicyDecision


class DecisionStore(Protocol):
    """节点运行器使用的审计决定真源接口。"""

    def save(self, *, run_id: str, step_id: str, decision: PolicyDecision) -> None:
        """先持久化决定，再允许调用方进入提交或记忆写入边界。"""

    def assert_decision(
        self,
        *,
        run_id: str,
        step_id: str,
        decision_ref: str,
        outcomes: Set[str] | None = None,
    ) -> PolicyDecision:
        """验证决定的完整性、归属和可接受结果，并返回独立合同副本。"""


class DecisionAccessError(ValueError):
    """审计决定缺失、损坏或不属于当前运行步骤时抛出。"""


def _checksum(payload: dict[str, object]) -> str:
    """用规范 JSON 计算决定记录的 SHA-256 摘要，不写入原始输出或上下文。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _same_logical_decision(left: dict[str, object], right: dict[str, object]) -> bool:
    """比较可重试决定的稳定语义，忽略每次评估自动生成的 decidedAt。"""
    left_stable = dict(left)
    right_stable = dict(right)
    left_stable.pop("decidedAt", None)
    right_stable.pop("decidedAt", None)
    return left_stable == right_stable


class InMemoryDecisionStore:
    """供最小运行器和单元测试使用的进程内审计决定仓库。"""

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, str, dict[str, object], str]] = {}

    def save(self, *, run_id: str, step_id: str, decision: PolicyDecision) -> None:
        """保存不可变决定；同标识重复写入仅接受完全相同的记录。"""
        payload = decision.model_dump(by_alias=True, mode="json")
        digest = _checksum(payload)
        record = (run_id, step_id, deepcopy(payload), digest)
        existing = self._records.get(decision.decision_id)
        if existing is None:
            self._records[decision.decision_id] = record
            return
        if existing[:2] != record[:2] or not _same_logical_decision(existing[2], record[2]):
            raise DecisionAccessError(f"audit decision already exists with different payload: {decision.decision_id}")

    def assert_decision(
        self,
        *,
        run_id: str,
        step_id: str,
        decision_ref: str,
        outcomes: Set[str] | None = None,
    ) -> PolicyDecision:
        """按当前运行步骤读取并验证内存决定，不允许跨步骤复用。"""
        record = self._records.get(decision_ref)
        if record is None:
            raise DecisionAccessError(f"audit decision does not exist: {decision_ref}")
        owner_run_id, owner_step_id, payload, digest = record
        return self._validated(
            run_id=run_id,
            step_id=step_id,
            decision_ref=decision_ref,
            owner_run_id=owner_run_id,
            owner_step_id=owner_step_id,
            payload=payload,
            digest=digest,
            outcomes=outcomes,
        )

    @staticmethod
    def _validated(
        *,
        run_id: str,
        step_id: str,
        decision_ref: str,
        owner_run_id: str,
        owner_step_id: str,
        payload: dict[str, object],
        digest: str,
        outcomes: Set[str] | None,
    ) -> PolicyDecision:
        if owner_run_id != run_id:
            raise DecisionAccessError(
                f"audit decision {decision_ref} belongs to run {owner_run_id}, not requested run {run_id}"
            )
        if owner_step_id != step_id:
            raise DecisionAccessError(
                f"audit decision {decision_ref} belongs to step {owner_step_id}, not requested step {step_id}"
            )
        if _checksum(payload) != digest:
            raise DecisionAccessError(f"audit decision integrity verification failed: {decision_ref}")
        try:
            decision = PolicyDecision.model_validate(deepcopy(payload))
        except Exception as exc:
            raise DecisionAccessError(f"audit decision is malformed: {decision_ref}") from exc
        if decision.decision_id != decision_ref:
            raise DecisionAccessError(f"audit decision identifier does not match record: {decision_ref}")
        if outcomes is not None and decision.outcome not in outcomes:
            raise DecisionAccessError(
                f"audit decision {decision_ref} has unexpected outcome {decision.outcome}"
            )
        return decision


class SQLiteDecisionStore(InMemoryDecisionStore):
    """可跨进程恢复的 SQLite 审计决定真源。

    表中只保存 ``PolicyDecision`` 的治理合同与归属元数据。`subjectRef`、策略标识、
    评分等已经是引用或统计字段；Agent 输出、ContextPack、记忆正文和工具参数禁止进入。
    """

    def __init__(self, *, db_path: str | Path) -> None:
        super().__init__()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS acg_audit_decisions (
                decision_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                decision_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self._connection.commit()

    def save(self, *, run_id: str, step_id: str, decision: PolicyDecision) -> None:
        """原子保存决定；同一决定标识不能被后续不同内容改写。"""
        payload = decision.model_dump(by_alias=True, mode="json")
        digest = _checksum(payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT run_id, step_id, decision_json, decision_hash FROM acg_audit_decisions WHERE decision_id = ?",
                (decision.decision_id,),
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """INSERT INTO acg_audit_decisions(
                        decision_id, run_id, step_id, decision_json, decision_hash
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (decision.decision_id, run_id, step_id, encoded, digest),
                )
            else:
                owner_run_id, owner_step_id, existing_json, _existing_hash = (str(item) for item in row)
                try:
                    existing_payload = json.loads(existing_json)
                except Exception as exc:
                    raise DecisionAccessError(
                        f"audit decision is malformed: {decision.decision_id}"
                    ) from exc
                if (
                    owner_run_id != run_id
                    or owner_step_id != step_id
                    or not isinstance(existing_payload, dict)
                    or not _same_logical_decision(existing_payload, payload)
                ):
                    raise DecisionAccessError(
                        f"audit decision already exists with different payload: {decision.decision_id}"
                    )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def assert_decision(
        self,
        *,
        run_id: str,
        step_id: str,
        decision_ref: str,
        outcomes: Set[str] | None = None,
    ) -> PolicyDecision:
        """读取并重算摘要后返回决定；任何损坏或归属错误均不可继续恢复。"""
        row = self._connection.execute(
            """SELECT run_id, step_id, decision_json, decision_hash
               FROM acg_audit_decisions WHERE decision_id = ?""",
            (decision_ref,),
        ).fetchone()
        if row is None:
            raise DecisionAccessError(f"audit decision does not exist: {decision_ref}")
        try:
            payload = json.loads(str(row[2]))
        except Exception as exc:
            raise DecisionAccessError(f"audit decision is malformed: {decision_ref}") from exc
        if not isinstance(payload, dict):
            raise DecisionAccessError(f"audit decision is malformed: {decision_ref}")
        return self._validated(
            run_id=run_id,
            step_id=step_id,
            decision_ref=decision_ref,
            owner_run_id=str(row[0]),
            owner_step_id=str(row[1]),
            payload=payload,
            digest=str(row[3]),
            outcomes=outcomes,
        )

    def close(self) -> None:
        """关闭独立审计数据库连接。"""
        self._connection.close()


__all__ = [
    "DecisionAccessError",
    "DecisionStore",
    "InMemoryDecisionStore",
    "SQLiteDecisionStore",
]
