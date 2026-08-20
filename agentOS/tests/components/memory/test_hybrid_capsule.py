"""Hybrid retrieval and long-phase capsule behavior."""

from __future__ import annotations

from components.memory.retrieval import DeterministicEmbeddingAdapter, InMemoryVectorIndex
from components.memory.service import MemoryService
from components.memory.store import MemoryStore
from contracts.memory import MemoryQuery, MemoryRecord, MemoryType


def _record(memory_id: str, content: str, *, scope: str = "run-1") -> MemoryRecord:
    return MemoryRecord(
        memoryId=memory_id,
        memoryType=MemoryType.EVIDENCE,
        content={"text": content},
        scope=scope,
    )


def test_hybrid_retrieval_admits_scope_before_bm25_vector_rrf() -> None:
    service = MemoryService()
    service.remember(_record("relevant", "atomic scheduler lease capacity"))
    service.remember(_record("other", "creative writing outline"))
    service.remember(_record("foreign", "atomic scheduler lease capacity", scope="run-2"))

    records, hits, event = service.hybrid_search(
        MemoryQuery(query="scheduler lease", scope="run-1", limit=2)
    )

    assert records[0].memory_id == "relevant"
    assert {record.memory_id for record in records} == {"relevant", "other"}
    assert {hit.memory_id for hit in hits} == {"relevant", "other"}
    assert "foreign" not in event.hit_refs
    assert event.mode == "bm25_vector_rrf"


def test_vector_index_can_be_rebuilt_from_authoritative_store() -> None:
    store = MemoryStore()
    store.put(_record("one", "resource heartbeat"))
    store.put(_record("two", "phase capsule"))
    rebuilt = MemoryService(
        store=store,
        embedding_adapter=DeterministicEmbeddingAdapter(),
        vector_index=InMemoryVectorIndex(),
    )

    assert rebuilt.rebuild_vector_index() == 2
    records, _, _ = rebuilt.hybrid_search(MemoryQuery(query="capsule", scope="run-1"))
    assert records[0].memory_id == "two"


def test_fifty_step_phase_capsule_keeps_references_and_respects_budget() -> None:
    service = MemoryService()
    refs = []
    for index in range(50):
        record = _record(f"memory:run-1:step-{index:02d}", f"fact {index:02d}")
        service.remember(record)
        refs.append(record.memory_id)

    capsule = service.create_phase_capsule(
        run_id="run-1",
        phase_id="research",
        source_memory_refs=refs,
        token_budget=300,
    )

    assert len(capsule.source_memory_refs) == 50
    assert capsule.token_count <= 300
    assert service._store.get(capsule.capsule_id) is not None
