"""供 Agent 运行期补读已授权上游引用的受控读取器。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .broker import CommunicationAccessError, CommunicationBroker
from .contracts import ContextPack


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
    ) -> None:
        self._broker = broker
        self._run_id = run_id
        self._consumer_step_id = consumer_step_id
        self._output_refs = dict(output_refs)
        self._max_tokens = max_tokens
        self._packs: list[ContextPack] = []

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
    ) -> ContextPack:
        """读取一个已授权上游的指定字段，并缓存结果供节点提交血缘登记。"""
        output_ref = self._output_refs.get(producer_step_id)
        if output_ref is None:
            raise CommunicationAccessError(
                "TOPOLOGY_DENIED",
                "producer step is not available to this communication reader",
            )
        pack = await self._broker.read_reference(
            run_id=self._run_id,
            consumer_step_id=self._consumer_step_id,
            output_ref=output_ref,
            requested_fields=fields,
            max_tokens=self._max_tokens,
            reason=reason,
        )
        self._packs.append(pack)
        return pack

    async def read_page(
        self, producer_step_id: str, fields: Iterable[str], *, cursor: str | None = None,
        page_tokens: int, reason: str = "",
    ) -> tuple[ContextPack, str | None]:
        """Read one authorized page; retain its pack for normal provenance recording."""
        output_ref = self._output_refs.get(producer_step_id)
        if output_ref is None:
            raise CommunicationAccessError(
                "TOPOLOGY_DENIED", "producer step is not available to this communication reader"
            )
        pack, next_cursor = await self._broker.read_reference_page(
            run_id=self._run_id, consumer_step_id=self._consumer_step_id,
            output_ref=output_ref, requested_fields=fields, cursor=cursor,
            page_tokens=page_tokens, reason=reason,
        )
        self._packs.append(pack)
        return pack, next_cursor

    def drain_packs(self) -> list[ContextPack]:
        """领取本节点成功补读的 ContextPack，避免重复登记血缘。"""
        packs = list(self._packs)
        self._packs.clear()
        return packs


__all__ = ["CommunicationReader"]
