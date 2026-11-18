"""通信部件的公共 Facade。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contracts.communication import MessageEnvelope

from .contracts import ContextPack, estimate_tokens
from .provenance import ProvenanceLedger


class CommunicatorService:
    """记录通信生产与消费血缘；正文读取和组装统一由 Broker 完成。

    实例维护按运行隔离的内存血缘账本，但不执行 HTTP、队列或 WebSocket 投递；
    可靠传输、持久化及跨协程同步仍是应用层适配器的职责。
    """

    def __init__(
        self,
        *,
        run_id: str = "",
        mission_id: str = "",
        ledger: ProvenanceLedger | None = None,
    ) -> None:
        """服务使用 run 隔离账本；注入账本时先确认其归属，避免恢复串线。"""
        active_ledger = ledger or ProvenanceLedger(run_id=run_id, mission_id=mission_id)
        if active_ledger.run_id != run_id or active_ledger.mission_id != mission_id:
            raise ValueError("provenance ledger ownership does not match communicator run")
        self._ledger = active_ledger
        # 事件按步骤归属领取，而非使用全局游标。并行步骤在 Agent 调用期间会交错
        # 记账；全局游标会把先完成节点之外的事件错误投影到当前节点 Trace。
        self._drained_event_ids: set[str] = set()

    def compose(self, message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
        """把消息标识、主题、发送方和载荷封装为 ``MessageEnvelope``。

        返回新合同对象且不执行网络或队列副作用；字段非法时由合同校验错误上抛。
        输入载荷不在服务内变更，固定字段装配的时间与空间复杂度均为 O(1)。
        """
        return MessageEnvelope(messageId=message_id, topic=topic, sender=sender, recipient=recipient, payload=payload)

    def record_production(self, step_id: str, output: dict[str, Any], *, agent_name: str = "", attempt: int = 1, operation_id: str = "") -> None:
        """为 ``step_id`` 的输出登记字段、Token 与证据血缘。

        该调用会向内部账本追加生产事件而不修改 ``output``。
        账本错误或无效输入保持原样上抛。
        """
        raw = output.get("evidence_refs") or output.get("evidenceRefs") or []
        evidence_refs = []
        for item in raw if isinstance(raw, list) else []:
            ref = item if isinstance(item, str) else item.get("id") if isinstance(item, Mapping) else None
            if ref and str(ref) not in evidence_refs:
                evidence_refs.append(str(ref))
        self.provenance.record_production(step_id, output, estimate_tokens(output),
            agent_name=agent_name, attempt=attempt, evidence_refs=evidence_refs, operation_id=operation_id)

    def record_context_consumption(self, pack: ContextPack, *, operation_id: str = "") -> None:
        """把已获准的 ContextPack 写入消费与交互血缘账本。

        Broker 已完成正文读取和字段裁剪；本方法只把 ContextPack 中的字段名、校验
        摘要、引用和统计写入账本。它不保存 ``data`` 或 ``sourceData`` 正文，且用
        节点提交标识派生两个角色不同的幂等键，恢复重放不会生成重复血缘事件。
        """
        fields_by_producer = {
            source_step_id: list(source_data)
            for source_step_id, source_data in pack.source_data.items()
        }
        consumption_operation = f"{operation_id}:consume" if operation_id else ""
        interaction_operation = f"{operation_id}:interact" if operation_id else ""
        self.provenance.record_consumption(
            pack.step_id,
            list(pack.source_step_ids),
            list(pack.data),
            fields_by_producer=fields_by_producer,
            data=pack.data,
            tokens_delivered=pack.tokens_delivered,
            tokens_available=pack.tokens_available,
            saving_ratio=pack.saving_ratio,
            contract_status=pack.contract_status,
            operation_id=consumption_operation,
        )
        self.provenance.record_interaction(
            producer_step_ids=list(pack.source_step_ids),
            consumer_step_id=pack.step_id,
            fields_by_producer=fields_by_producer,
            evidence_refs=list(pack.evidence_refs),
            tokens_delivered=pack.tokens_delivered,
            tokens_available=pack.tokens_available,
            saving_ratio=pack.saving_ratio,
            operation_id=interaction_operation,
        )

    @property
    def provenance(self) -> ProvenanceLedger:
        """返回本服务持有的可导出内存血缘账本引用。

        返回的不是副本，调用者可读取事件或验证完整性，但直接修改公开列表可能
        破坏链式不变量；并发读取与写入须由调用方协调。
        """
        return self._ledger

    def drain_provenance_events(self, *, step_id: str | None = None) -> list[dict[str, Any]]:
        """领取尚未投影且归属当前步骤的安全血缘事件。

        ``step_id`` 存在时，生产事件按生产者归属，消费与交互事件按消费者归属；
        这样并行节点即使交错执行也不会互相吞掉 Trace。省略它仅为兼容旧调用，
        会领取所有尚未投影的事件。
        """
        events = self.provenance.trace_events()
        owned: list[dict[str, Any]] = []
        for event in events:
            payload = event["payload"]
            event_id = payload["eventId"]
            if event_id in self._drained_event_ids:
                continue
            if step_id is not None and not self._belongs_to_step(event, step_id):
                continue
            self._drained_event_ids.add(event_id)
            owned.append(event)
        return owned

    @staticmethod
    def _belongs_to_step(event: dict[str, Any], step_id: str) -> bool:
        """判断安全投影是否归属步骤；只查看投影元数据，不读取正文。"""
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return False
        return payload.get("producerStepId") == step_id or payload.get("consumerStepId") == step_id
