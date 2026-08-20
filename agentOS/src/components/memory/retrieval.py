"""Lexical/vector retrieval over SQLite-authoritative memory records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import hashlib
import json
import math
import re
from typing import Protocol

from contracts.memory import MemoryQuery, MemoryRecord


class EmbeddingAdapter(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


class VectorIndex(Protocol):
    def upsert(self, memory_id: str, vector: Sequence[float]) -> None: ...
    def search(self, vector: Sequence[float], limit: int) -> list[tuple[str, float]]: ...


class DeterministicEmbeddingAdapter:
    """Small offline adapter for tests; production may inject a provider adapter."""

    def __init__(self, dimensions: int = 32) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            values[int.from_bytes(digest[:2], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class InMemoryVectorIndex:
    """Derived index containing only memory ids and vectors."""

    def __init__(self) -> None:
        self._vectors: dict[str, tuple[float, ...]] = {}

    def upsert(self, memory_id: str, vector: Sequence[float]) -> None:
        self._vectors[memory_id] = tuple(float(value) for value in vector)

    def search(self, vector: Sequence[float], limit: int) -> list[tuple[str, float]]:
        query = tuple(float(value) for value in vector)
        scored = [
            (memory_id, max(0.0, sum(left * right for left, right in zip(query, candidate))))
            for memory_id, candidate in self._vectors.items()
        ]
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]


def record_text(record: MemoryRecord) -> str:
    return json.dumps(record.content, ensure_ascii=False, sort_keys=True)


def lexical_scores(records: list[MemoryRecord], query: str) -> dict[str, float]:
    terms = _tokens(query)
    if not terms:
        return {record.memory_id: 0.0 for record in records}
    scores: dict[str, float] = {}
    for record in records:
        counts = Counter(_tokens(record_text(record)))
        scores[record.memory_id] = sum(counts[term] for term in terms) / max(sum(counts.values()), 1)
    return scores


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


def retrieve(records: list[MemoryRecord], query: MemoryQuery) -> list[MemoryRecord]:
    """按类型、范围和标签对本地记录作确定性过滤并限制数量。

    返回保留输入相对顺序的前 ``query.limit`` 条，未做向量相似度、权限或过期
    处理；这些边界由外部检索适配器负责。时间 O(n)，返回列表额外空间 O(k)。
    """
    selected = [record for record in records if (not query.memory_types or record.memory_type in query.memory_types) and (query.scope is None or record.scope == query.scope) and set(query.tags).issubset(record.tags)]
    return selected[:query.limit]


# TODO: 接入向量检索适配器后，根据嵌入相似度和权限过滤执行召回。
# TODO(可迁移): 可通过 Adapter 借鉴 Mem0 的记忆合并/向量召回及 Haystack 的
# DocumentStore/Retriever 模式；MemoryService 必须保持唯一读写入口，外部存储不得绕过
# 准入、权限、审计或生命周期。代码级复用前须复核 Apache-2.0 的 LICENSE、NOTICE 与子依赖。
