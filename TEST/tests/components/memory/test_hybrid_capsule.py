"""Hybrid retrieval and long-phase capsule behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    assert {record.memory_id for record in records} == {"relevant"}
    assert {hit.memory_id for hit in hits} == {"relevant"}
    assert "foreign" not in event.hit_refs
    assert event.mode == "bm25"
    assert event.fallback_reason == "SEMANTIC_MODEL_NOT_CONFIGURED"


@pytest.mark.parametrize("query", ["unrelated vaccination", "   "])
def test_no_relevant_memory_returns_empty_instead_of_filling_the_limit(query):
    service = MemoryService()
    service.remember(_record("first", "scheduler lease capacity"))
    service.remember(_record("second", "repository source inspection"))

    records, hits, event = service.hybrid_search(MemoryQuery(query=query, scope="run-1", limit=10))

    assert records == hits == []
    assert event.hit_refs == [] and service.last_retrieval_event == event


def test_vector_only_match_is_retained_without_adding_zero_or_nonfinite_similarity_rows():
    class Embedding:
        def embed(self, text):
            return [1.0]

    class Index:
        def upsert(self, memory_id, vector):
            pass

        def search(self, vector, limit):
            return [("semantic", 0.8), ("foreign", 0.9), ("expired", 0.9),
                ("wrong-type", 0.9), ("zero", 0.0), ("negative", -0.1), ("nan", float("nan"))]

    service = MemoryService(embedding_adapter=Embedding(), vector_index=Index())
    for memory_id in ("semantic", "zero", "negative", "nan"):
        service.remember(_record(memory_id, "automobile repair"))
    service.remember(_record("foreign", "automobile repair", scope="run-2"))
    expired = _record("expired", "automobile repair").model_copy(update={
        "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    service.remember(expired)
    service.remember(_record("wrong-type", "automobile repair").model_copy(update={"memory_type": MemoryType.EPISODIC}))

    records, hits, event = service.hybrid_search(MemoryQuery(query="car maintenance", scope="run-1",
        memoryTypes=[MemoryType.EVIDENCE], limit=10))

    assert [record.memory_id for record in records] == ["semantic"]
    assert len(hits) == 1 and hits[0].lexical_score == 0 and hits[0].vector_score == 0.8
    assert event.mode == "bm25_vector_rrf" and event.hit_refs == ["semantic"]


def test_unavailable_vector_index_falls_back_only_to_actual_lexical_matches():
    class BrokenIndex(InMemoryVectorIndex):
        def search(self, vector, limit):
            raise OSError("unavailable")

    service = MemoryService(embedding_adapter=DeterministicEmbeddingAdapter(), vector_index=BrokenIndex())
    service.remember(_record("relevant", "scheduler lease capacity"))
    service.remember(_record("unrelated", "creative writing"))

    records, hits, event = service.hybrid_search(MemoryQuery(query="lease", scope="run-1", limit=10))

    assert [record.memory_id for record in records] == ["relevant"]
    assert [hit.memory_id for hit in hits] == ["relevant"]
    assert event.mode == "lexical_fallback" and event.fallback_reason == "VECTOR_INDEX_UNAVAILABLE"


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
