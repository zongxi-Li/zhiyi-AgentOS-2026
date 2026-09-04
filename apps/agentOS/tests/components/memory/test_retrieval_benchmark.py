from __future__ import annotations

from components.memory.service import MemoryService
from contracts.memory import MemoryQuery, MemoryRecord, MemoryType


_DOCUMENTS = {
    "scheduler": "Redis Lua provides atomic scheduler lease capacity allocation",
    "capsule": "Phase capsule preserves goals constraints and evidence references",
    "resource": "Resource heartbeat expires and health becomes unknown after restart",
    "evolution": "Evolution policy version approval only changes future general runs",
    "checkpoint": "Checkpoint recovery resumes the same workflow run after review",
    "调度": "Redis Lua 脚本保证调度租约容量原子分配",
    "胶囊": "阶段胶囊保留目标约束证据引用和开放问题",
    "资源": "资源心跳过期后健康状态恢复为未知",
    "演化": "演化策略版本审批只影响未来通用任务",
    "恢复": "检查点支持人工审核后恢复同一个工作流运行",
}

_QUERIES = {
    "atomic lease capacity": "scheduler",
    "phase goals evidence": "capsule",
    "heartbeat unknown restart": "resource",
    "future policy version": "evolution",
    "checkpoint workflow review": "checkpoint",
    "原子调度租约容量": "调度",
    "阶段胶囊目标证据": "胶囊",
    "资源心跳健康未知": "资源",
    "演化版本未来任务": "演化",
    "检查点审核恢复": "恢复",
}


def _record(memory_id: str, content: str, scope: str = "tenant:alpha:user:alice") -> MemoryRecord:
    return MemoryRecord(
        memoryId=memory_id,
        memoryType=MemoryType.EVIDENCE,
        content={"text": content},
        scope=scope,
    )


def test_fixed_bilingual_hybrid_retrieval_benchmark() -> None:
    service = MemoryService()
    for memory_id, content in _DOCUMENTS.items():
        service.remember(_record(memory_id, content))

    reciprocal_ranks: list[float] = []
    recalled_at_five = 0
    for query, relevant_id in _QUERIES.items():
        records, _, _ = service.hybrid_search(
            MemoryQuery(query=query, scope="tenant:alpha:user:alice", limit=10)
        )
        ranked = [record.memory_id for record in records]
        rank = ranked.index(relevant_id) + 1
        recalled_at_five += int(rank <= 5)
        reciprocal_ranks.append(1.0 / rank)

    recall_at_five = recalled_at_five / len(_QUERIES)
    mrr_at_ten = sum(reciprocal_ranks) / len(reciprocal_ranks)
    assert recall_at_five >= 0.85
    assert mrr_at_ten >= 0.75


def test_hybrid_retrieval_has_zero_cross_user_and_tenant_recall() -> None:
    service = MemoryService()
    service.remember(_record("alice", "private atomic lease evidence"))
    service.remember(
        _record("bob", "private atomic lease evidence", scope="tenant:alpha:user:bob")
    )
    service.remember(
        _record("other-tenant", "private atomic lease evidence", scope="tenant:beta:user:alice")
    )

    records, _, _ = service.hybrid_search(
        MemoryQuery(query="private atomic lease evidence", scope="tenant:alpha:user:alice")
    )

    assert [record.memory_id for record in records] == ["alice"]
