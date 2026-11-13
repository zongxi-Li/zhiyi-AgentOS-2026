"""供 Agent 运行期补读已授权上游引用的受控读取器。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .broker import CommunicationAccessError, CommunicationBroker
from .contracts import ContextPack
from contracts.request_budget import SupplementalReadBudget


class CommunicationReader:
    """把 Agent 的字段补读限制在当前节点已声明的上游输出引用内。"""

    def __init__(
        self,
        *,
        broker: CommunicationBroker,
        run_id: str,
        consumer_step_id: str,
        output_refs: Mapping[str, str],
        max_tokens: int | None,
        model_budget: SupplementalReadBudget | None = None,
        on_read=None,
    ) -> None:
        self._broker = broker
        self._run_id = run_id
        self._consumer_step_id = consumer_step_id
        self._output_refs = dict(output_refs)
        self._max_tokens = max_tokens
        self._packs: list[ContextPack] = []
        self.model_budget = model_budget
        self._on_read = on_read
        self._completed_operations: set[str] = set()
        self._evidence_refs: list[str] = []

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(self._evidence_refs)

    def describe_sources(self) -> list[dict]:
        return [self._broker.describe_reference(run_id=self._run_id,
            consumer_step_id=self._consumer_step_id, output_ref=reference)
            for reference in self._output_refs.values()]

    @property
    def operation_store(self):
        """Reuse the existing run-owned WAL for model decisions when supported."""
        store = self._broker.value_store
        return store if callable(getattr(store, "get_tool_value", None)) else None

    def _record(self, pack: ContextPack, operation_id: str) -> None:
        if operation_id and operation_id in self._completed_operations:
            return
        self._evidence_refs.extend(ref for ref in pack.evidence_refs if ref not in self._evidence_refs)
        if self._on_read is not None and operation_id:
            self._on_read(pack, operation_id)
        else:
            self._packs.append(pack)
        if operation_id:
            self._completed_operations.add(operation_id)

    @property
    def available_sources(self) -> tuple[str, ...]:
        """返回当前节点可补读的生产步骤标识，不暴露其它运行状态。"""
        return tuple(self._output_refs)

    async def read(
        self,
        producer_step_id: str,
        fields: Iterable[str],
        *,
        reason: str = "",
        operation_id: str = "",
    ) -> ContextPack:
        """读取一个已授权上游的指定字段，并缓存结果供节点提交血缘登记。"""
        output_ref = self._output_refs.get(producer_step_id)
        if output_ref is None:
            raise CommunicationAccessError(
                "TOPOLOGY_DENIED",
                "producer step is not available to this communication reader",
            )
        limit = self._max_tokens
        if self.model_budget is not None:
            limit = min(limit, self.model_budget.max_read_tokens) if limit is not None else self.model_budget.max_read_tokens
        pack = await self._broker.read_reference(
            run_id=self._run_id,
            consumer_step_id=self._consumer_step_id,
            output_ref=output_ref,
            requested_fields=fields,
            max_tokens=limit,
            reason=reason,
            operation_id=operation_id,
            supplemental_limit=self.model_budget.total_tokens if self.model_budget else None,
        )
        self._record(pack, operation_id)
        return pack

    async def read_page(
        self, producer_step_id: str, fields: Iterable[str], *, cursor: str | None = None,
        page_tokens: int, reason: str = "",
        operation_id: str = "",
    ) -> tuple[ContextPack, str | None]:
        """Read one authorized page; retain its pack for normal provenance recording."""
        output_ref = self._output_refs.get(producer_step_id)
        if output_ref is None:
            raise CommunicationAccessError(
                "TOPOLOGY_DENIED", "producer step is not available to this communication reader"
            )
        if ((self.model_budget is not None and page_tokens > self.model_budget.max_read_tokens)
                or (self._max_tokens is not None and page_tokens > self._max_tokens)):
            from .broker import EntropyBudgetExceededError
            raise EntropyBudgetExceededError("requested page exceeds frozen read budget")
        pack, next_cursor = await self._broker.read_reference_page(
            run_id=self._run_id, consumer_step_id=self._consumer_step_id,
            output_ref=output_ref, requested_fields=fields, cursor=cursor,
            page_tokens=page_tokens, reason=reason,
            operation_id=operation_id,
            supplemental_limit=self.model_budget.total_tokens if self.model_budget else None,
        )
        self._record(pack, operation_id)
        return pack, next_cursor

    def drain_packs(self) -> list[ContextPack]:
        """领取本节点成功补读的 ContextPack，避免重复登记血缘。"""
        packs = list(self._packs)
        self._packs.clear()
        return packs


__all__ = ["CommunicationReader"]
