"""ACG 节点运行期记忆边界测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from components.memory import MemoryService
from components.memory.store import SQLiteMemoryStore
from contracts.memory import MemoryPolicy, MemoryRecord, MemoryType


def _record(
    *,
    run_id: str,
    memory_id: str,
    memory_type: MemoryType = MemoryType.EPISODIC,
    expires_at: datetime | None = None,
) -> MemoryRecord:
    """构造测试用 run-scoped 情节记忆。"""
    return MemoryRecord(
        memoryId=memory_id,
        memoryType=memory_type,
        content={"fact": memory_id},
        scope=run_id,
        expiresAt=expires_at,
    )


def test_recall_for_step_never_returns_memory_from_another_run() -> None:
    """节点召回必须以 runId 锁定 scope，不能因查询命中而跨运行泄漏。"""
    memory = MemoryService()
    memory.remember(_record(run_id="run-a", memory_id="m-a"))
    memory.remember(_record(run_id="run-b", memory_id="m-b"))

    records = memory.recall_for_step(run_id="run-a", step_id="analysis", query="fact")

    assert [item.memory_id for item in records] == ["m-a"]


def test_recall_for_step_filters_expired_records() -> None:
    """失效记录不能继续注入 Agent 上下文，即使其 scope 与查询都匹配。"""
    memory = MemoryService()
    memory.remember(_record(run_id="run-a", memory_id="expired", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    memory.remember(_record(run_id="run-a", memory_id="live"))

    records = memory.recall_for_step(run_id="run-a", step_id="analysis", query="fact")

    assert [item.memory_id for item in records] == ["live"]


def test_recall_for_step_applies_type_limit_and_token_budget() -> None:
    """步骤策略必须先限定类别和数量，再保证召回正文不超过 Token 预算。"""
    memory = MemoryService()
    memory.remember(_record(run_id="run-a", memory_id="episodic-large"))
    memory.remember(
        _record(
            run_id="run-a",
            memory_id="semantic-small",
            memory_type=MemoryType.SEMANTIC,
        )
    )
    memory.remember(_record(run_id="run-a", memory_id="episodic-small"))

    records = memory.recall_for_step(
        run_id="run-a",
        step_id="analysis",
        query="fact",
        memory_types=[MemoryType.EPISODIC],
        limit=1,
        token_budget=10,
    )

    assert [item.memory_id for item in records] == ["episodic-large"]


def test_remember_step_output_writes_controlled_episodic_memory() -> None:
    """节点输出只能在已完成合同白名单裁剪后被记录成该 run 的情节记忆。"""
    memory = MemoryService()

    record = memory.remember_step_output(
        run_id="run-a",
        step_id="analysis",
        output={"answer": "safe"},
        policy=MemoryPolicy(policyId="episodic", allowedTypes=[MemoryType.EPISODIC]),
    )

    assert record is not None
    assert record.content == {"answer": "safe"}
    assert record.scope == "run-a"
    assert record.tags == ["execution", "analysis"]


def test_remember_step_output_returns_none_when_policy_rejects_write() -> None:
    """策略拒绝时不能留下记忆记录或可误导下游的 memoryRef。"""
    memory = MemoryService()

    record = memory.remember_step_output(
        run_id="run-a",
        step_id="analysis",
        output={"answer": "safe"},
        policy=MemoryPolicy(policyId="semantic-only", allowedTypes=[MemoryType.SEMANTIC]),
    )

    assert record is None
    assert memory.recall_for_step(run_id="run-a", step_id="analysis", query="safe") == []


def test_sqlite_memory_store_survives_reopen_for_same_run(tmp_path) -> None:
    """进程重建后，当前 run 的情节记忆必须仍可按范围召回。"""
    db_path = tmp_path / "memory.sqlite3"
    first = MemoryService(store=SQLiteMemoryStore(db_path=db_path))
    first.remember_step_output(
        run_id="run-a",
        step_id="extract",
        output={"title": "persisted"},
    )
    first._store.close()

    reopened_store = SQLiteMemoryStore(db_path=db_path)
    reopened = MemoryService(store=reopened_store)

    records = reopened.recall_for_step(run_id="run-a", step_id="deliver", query="persisted")
    assert [record.memory_id for record in records] == ["memory:run-a:extract"]
    reopened_store.close()
