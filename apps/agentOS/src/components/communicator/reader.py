"""供 Agent 运行期补读已授权上游引用的受控读取器。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .broker import CommunicationAccessError, CommunicationBroker, EntropyBudgetExceededError
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
        self._receipt_evidence_refs: set[str] = set()

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(self._evidence_refs)

    @property
    def receipt_evidence_refs(self) -> frozenset[str]:
        return frozenset(self._receipt_evidence_refs)

    def admit_receipt_reference(self, reference: str) -> None:
        self._receipt_evidence_refs.add(reference)
        if reference not in self._evidence_refs:
            self._evidence_refs.append(reference)

    def committed_receipt_refs(self, producers: set[str]) -> set[tuple[str, str]]:
        """Find receipts published by the committed outputs delivered to this reader."""
        delivered = {self._output_refs[step]: step for step in producers if step in self._output_refs}
        if not delivered or self.operation_store is None:
            return set()
        references = set()
        for commit in self.operation_store.list_node_commits(run_id=self._run_id):
            producer = delivered.get(commit.get("outputRef"))
            if not producer or commit.get("stage") != "committed" or commit.get("auditOutcome") != "allow":
                continue
            for record in (*(commit.get("toolCalls") or ()), *(commit.get("historicalToolEvidence") or ())):
                if record.get("runId") == self._run_id and record.get("stepId") == producer and record.get("receiptRef"):
                    references.add((producer, record["receiptRef"]))
        return references

    def describe_sources(self) -> list[dict]:
        return [self._broker.describe_reference(run_id=self._run_id,
            consumer_step_id=self._consumer_step_id, output_ref=reference,
            producer_step_id=producer)
            for producer, reference in self._output_refs.items()]

    def describe_path(self, producer_step_id: str, fields: Iterable[str], *, value_path=()) -> dict:
        output_ref = self._output_refs.get(producer_step_id)
        if output_ref is None:
            raise CommunicationAccessError("TOPOLOGY_DENIED", "producer step is not available to this communication reader")
        return self._broker.describe_reference_path(run_id=self._run_id, consumer_step_id=self._consumer_step_id,
            output_ref=output_ref, producer_step_id=producer_step_id, requested_fields=fields, value_path=value_path)

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
        if self.model_budget is not None and self.model_budget.max_read_tokens is not None:
            limit = min(limit, self.model_budget.max_read_tokens) if limit is not None else self.model_budget.max_read_tokens
        pack = await self._broker.read_reference(
            run_id=self._run_id,
            consumer_step_id=self._consumer_step_id,
            output_ref=output_ref,
            producer_step_id=producer_step_id,
            requested_fields=fields,
            max_tokens=limit,
            reason=reason,
            operation_id=operation_id,
            supplemental_limit=self.model_budget.total_tokens if self.model_budget else None,
            supplemental_read=True,
        )
        self._record(pack, operation_id)
        return pack

    async def read_page(
        self, producer_step_id: str, fields: Iterable[str], *, cursor: str | None = None,
        page_tokens: int, reason: str = "",
        operation_id: str = "",
        value_path: tuple[str | int, ...] = (),
    ) -> tuple[ContextPack, str | None]:
        """Read one authorized page; retain its pack for normal provenance recording."""
        output_ref = self._output_refs.get(producer_step_id)
        if output_ref is None:
            raise CommunicationAccessError(
                "TOPOLOGY_DENIED", "producer step is not available to this communication reader"
            )
        if ((self.model_budget is not None and self.model_budget.max_read_tokens is not None
                and page_tokens > self.model_budget.max_read_tokens)
                or (self._max_tokens is not None and page_tokens > self._max_tokens)):
            raise EntropyBudgetExceededError("requested page exceeds frozen read budget")
        pack, next_cursor = await self._broker.read_reference_page(
            run_id=self._run_id, consumer_step_id=self._consumer_step_id,
            output_ref=output_ref, requested_fields=fields, cursor=cursor,
            producer_step_id=producer_step_id,
            page_tokens=page_tokens, reason=reason,
            operation_id=operation_id,
            supplemental_limit=self.model_budget.total_tokens if self.model_budget else None,
            supplemental_read=True,
            value_path=value_path,
        )
        self._record(pack, operation_id)
        return pack, next_cursor

    def read_evidence_page(self, *, reference: str, producer_step_id: str, field: str,
                           value, cursor: str | None, page_tokens: int, operation_id: str):
        """Account for a page of a receipt already admitted by the tool session."""
        limit = self.model_budget or SupplementalReadBudget()
        caps = [value for value in (limit.max_read_tokens or limit.page_tokens, self._max_tokens) if value is not None]
        if not 1 <= page_tokens <= min(caps):
            raise EntropyBudgetExceededError("requested page exceeds frozen read budget")
        pack, next_cursor = self._broker.read_evidence_page(
            consumer_step_id=self._consumer_step_id, producer_step_id=producer_step_id,
            reference=reference, field=field, value=value, cursor=cursor, page_tokens=page_tokens,
            operation_id=operation_id, supplemental_limit=limit.total_tokens,
        )
        self._record(pack, operation_id)
        return pack, next_cursor

    def drain_packs(self) -> list[ContextPack]:
        """领取本节点成功补读的 ContextPack，避免重复登记血缘。"""
        packs = list(self._packs)
        self._packs.clear()
        return packs


__all__ = ["CommunicationReader"]
