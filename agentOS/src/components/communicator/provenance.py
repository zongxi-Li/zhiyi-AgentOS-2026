"""运行期通信血缘：生产、消费与交互事件的可验证账本。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def provenance_checksum(payload: Any) -> str:
    """以规范 JSON 为任意血缘载荷计算 SHA-256 完整性摘要。

    键排序和固定分隔符使等价数据产生稳定哈希，非 JSON 值转换为字符串；函数
    不持久化数据。时间与空间复杂度随编码大小为 O(n)。
    """
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _Event(BaseModel):
    """链式事件共有字段；previous_hash 使事件顺序也受完整性保护。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    event_id: str = Field(alias="eventId")
    run_id: str = Field(default="", alias="runId")
    mission_id: str = Field(default="", alias="missionId")
    # operationId 绑定节点提交。为空表示普通非执行期记账；非空时同一账本只接受
    # 一份语义完全相同的事件，用于进程在节点提交前中断后的安全重试。
    operation_id: str = Field(default="", alias="operationId")
    previous_hash: str = Field(default="", alias="previousHash")
    event_hash: str = Field(default="", alias="eventHash")
    created_at: datetime = Field(default_factory=_now, alias="createdAt")


class DataProductionEvent(_Event):
    """记录一个步骤产生字段、证据引用及其内容校验和的账本事件。

    事件哈希由账本写入时链接，模型禁止未知字段；实例本身不验证引用可访问性。
    """
    producer_step_id: str = Field(alias="producerStepId")
    agent_name: str = Field(default="", alias="agentName")
    attempt: int = 1
    checksum: str = ""
    field_names: list[str] = Field(default_factory=list, alias="fieldNames")
    token_size: int = Field(default=0, alias="tokenSize")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")


class DataConsumptionEvent(_Event):
    """记录一个消费者从哪些生产者取得哪些字段的账本事件。

    生产事件关联、Token 统计与合同状态由记录方提供，事件模型只约束可序列化
    结构，不重新读取生产者内容。
    """
    consumer_step_id: str = Field(alias="consumerStepId")
    producer_step_ids: list[str] = Field(default_factory=list, alias="producerStepIds")
    producer_event_ids: list[str] = Field(default_factory=list, alias="producerEventIds")
    fields_by_producer: dict[str, list[str]] = Field(default_factory=dict, alias="fieldsByProducer")
    consumed_fields: list[str] = Field(default_factory=list, alias="consumedFields")
    tokens_delivered: int = Field(default=0, alias="tokensDelivered")
    tokens_available: int = Field(default=0, alias="tokensAvailable")
    saving_ratio: float = Field(default=0.0, alias="savingRatio")
    checksum: str = ""
    contract_status: str = Field(default="valid", alias="contractStatus")


class RuntimeInteraction(_Event):
    """记录一次跨步骤上下文交互及其字段和证据边界。

    它是生产、消费事件之外的审计投影，依赖账本补齐事件链哈希；不表示网络
    已投递成功或外部系统已确认接收。
    """
    interaction_id: str = Field(alias="interactionId")
    producer_step_ids: list[str] = Field(default_factory=list, alias="producerStepIds")
    consumer_step_id: str = Field(alias="consumerStepId")
    fields_by_producer: dict[str, list[str]] = Field(default_factory=dict, alias="fieldsByProducer")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")
    tokens_delivered: int = Field(default=0, alias="tokensDelivered")
    tokens_available: int = Field(default=0, alias="tokensAvailable")
    saving_ratio: float = Field(default=0.0, alias="savingRatio")


class ProvenanceIntegrityError(ValueError):
    """持久化血缘事件无法通过哈希链或运行归属校验时抛出。"""


class ProvenanceLedger:
    """按运行隔离地维护生产、消费和交互事件的哈希链账本。

    每次记录都会以前一事件哈希封存当前事件；实例仅保存内存状态且没有锁，
    多线程写入、持久化和跨进程完整性由调用方或外部存储负责。
    """
    def __init__(
        self,
        *,
        run_id: str = "",
        mission_id: str = "",
        event_sink: Callable[[_Event], None] | None = None,
    ) -> None:
        self.run_id, self.mission_id, self._seq, self._tail_hash = run_id, mission_id, 0, ""
        self.productions: list[DataProductionEvent] = []
        self.consumptions: list[DataConsumptionEvent] = []
        self.interactions: list[RuntimeInteraction] = []
        self._event_sink = event_sink

    def _seal(self, event: _Event) -> None:
        event.previous_hash = self._tail_hash
        event.event_hash = provenance_checksum(self._hashed_payload(event))
        self._tail_hash = event.event_hash

    def _append(self, event: _Event, destination: list[_Event]) -> None:
        """先持久化已封存事件，再更新内存账本，避免内存状态伪装为已落盘。"""
        if self._event_sink is not None:
            self._event_sink(event)
        destination.append(event)

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:06d}"

    def _operation_event(self, operation_id: str) -> _Event | None:
        """读取同一提交已经封存的事件；空操作标识不启用执行期幂等规则。"""
        if not operation_id:
            return None
        return next(
            (
                event
                for event in [*self.productions, *self.consumptions, *self.interactions]
                if event.operation_id == operation_id
            ),
            None,
        )

    @staticmethod
    def _hashed_payload(event: _Event) -> dict[str, Any]:
        """生成事件哈希输入，并兼容未声明 operationId 的历史账本。

        旧版本创建的 JSON 没有 ``operationId``。Pydantic 读取它时会补上默认空值，
        若直接重新序列化就会改变历史哈希。因此只有新事件显式设置过该字段时才
        将其参与摘要；新旧账本可以在同一恢复链中继续验证和追加。
        """
        payload = event.model_dump(by_alias=True, mode="json", exclude={"event_hash"})
        if not event.operation_id and "operation_id" not in event.model_fields_set:
            payload.pop("operationId", None)
        return payload

    def record_production(self, step_id: str, output: dict[str, Any], token_size: int, *, agent_name: str = "", attempt: int = 1, evidence_refs: list[str] | None = None, operation_id: str = "") -> DataProductionEvent:
        """记录 ``step_id`` 产生的输出字段并返回已封存的生产事件。

        输出校验和、字段名和证据引用被写入事件，再追加到 ``productions``；输入
        输出不被修改。序列化规模为 n 时复杂度 O(n)，并发追加需调用方同步。
        """
        checksum = provenance_checksum(output)
        normalized_evidence = list(dict.fromkeys(evidence_refs or []))
        existing = self._operation_event(operation_id)
        if existing is not None:
            if (
                isinstance(existing, DataProductionEvent)
                and existing.producer_step_id == step_id
                and existing.agent_name == agent_name
                and existing.attempt == attempt
                and existing.checksum == checksum
                and existing.field_names == sorted(output)
                and existing.token_size == token_size
                and existing.evidence_refs == normalized_evidence
            ):
                return existing
            raise ProvenanceIntegrityError(
                f"provenance operation {operation_id} already exists with different payload"
            )
        event = DataProductionEvent(eventId=self._next_id("prod"), runId=self.run_id, missionId=self.mission_id, operationId=operation_id, producerStepId=step_id, agentName=agent_name, attempt=attempt, checksum=checksum, fieldNames=sorted(output), tokenSize=token_size, evidenceRefs=normalized_evidence)
        self._seal(event); self._append(event, self.productions)
        return event

    def record_consumption(self, step_id: str, producer_step_ids: list[str], consumed_fields: list[str], *, fields_by_producer: dict[str, list[str]], data: dict[str, Any], tokens_delivered: int, tokens_available: int, saving_ratio: float, contract_status: str = "valid", operation_id: str = "") -> DataConsumptionEvent:
        """记录消费者取得字段的来源、内容摘要和预算统计。

        生产步骤与字段会去重，并关联当前已知的最新生产事件；返回封存后追加的
        消费事件。缺少生产事件不会报错而是省略关联，复杂度 O(p + n)。
        """
        producer_ids = list(dict.fromkeys(producer_step_ids))
        latest = {event.producer_step_id: event.event_id for event in self.productions}
        producer_event_ids = [latest[source] for source in producer_ids if source in latest]
        normalized_fields = sorted(set(consumed_fields))
        checksum = provenance_checksum(data)
        existing = self._operation_event(operation_id)
        if existing is not None:
            if (
                isinstance(existing, DataConsumptionEvent)
                and existing.consumer_step_id == step_id
                and existing.producer_step_ids == producer_ids
                and existing.producer_event_ids == producer_event_ids
                and existing.fields_by_producer == fields_by_producer
                and existing.consumed_fields == normalized_fields
                and existing.tokens_delivered == tokens_delivered
                and existing.tokens_available == tokens_available
                and existing.saving_ratio == saving_ratio
                and existing.checksum == checksum
                and existing.contract_status == contract_status
            ):
                return existing
            raise ProvenanceIntegrityError(
                f"provenance operation {operation_id} already exists with different payload"
            )
        event = DataConsumptionEvent(eventId=self._next_id("cons"), runId=self.run_id, missionId=self.mission_id, operationId=operation_id, consumerStepId=step_id, producerStepIds=producer_ids, producerEventIds=producer_event_ids, fieldsByProducer=fields_by_producer, consumedFields=normalized_fields, tokensDelivered=tokens_delivered, tokensAvailable=tokens_available, savingRatio=saving_ratio, checksum=checksum, contractStatus=contract_status)
        self._seal(event); self._append(event, self.consumptions)
        return event

    def record_interaction(self, *, producer_step_ids: list[str], consumer_step_id: str, fields_by_producer: dict[str, list[str]], evidence_refs: list[str], tokens_delivered: int, tokens_available: int, saving_ratio: float, operation_id: str = "") -> RuntimeInteraction:
        """记录一次生产者到消费者的上下文交互并返回封存事件。

        生产者和证据引用会去重，返回事件追加到 ``interactions``；该记录不执行
        真实消息投递或证据验证。处理复杂度 O(p + e)，并发调用由调用方同步。
        """
        normalized_producers = list(dict.fromkeys(producer_step_ids))
        normalized_evidence = list(dict.fromkeys(evidence_refs))
        existing = self._operation_event(operation_id)
        if existing is not None:
            if (
                isinstance(existing, RuntimeInteraction)
                and existing.producer_step_ids == normalized_producers
                and existing.consumer_step_id == consumer_step_id
                and existing.fields_by_producer == fields_by_producer
                and existing.evidence_refs == normalized_evidence
                and existing.tokens_delivered == tokens_delivered
                and existing.tokens_available == tokens_available
                and existing.saving_ratio == saving_ratio
            ):
                return existing
            raise ProvenanceIntegrityError(
                f"provenance operation {operation_id} already exists with different payload"
            )
        event_id = self._next_id("int")
        event = RuntimeInteraction(eventId=event_id, interactionId=event_id, runId=self.run_id, missionId=self.mission_id, operationId=operation_id, producerStepIds=normalized_producers, consumerStepId=consumer_step_id, fieldsByProducer=fields_by_producer, evidenceRefs=normalized_evidence, tokensDelivered=tokens_delivered, tokensAvailable=tokens_available, savingRatio=saving_ratio)
        self._seal(event); self._append(event, self.interactions)
        return event

    def verify_integrity(self) -> bool:
        """按事件标识重放哈希链，验证当前账本是否保持完整。

        任一前序哈希或事件哈希不符即返回 ``False``，空账本返回 ``True``；方法
        不修复损坏数据。设事件数为 n、总编码大小为 m，复杂度 O(n log n + m)。
        """
        previous = ""
        events = sorted([*self.productions, *self.consumptions, *self.interactions], key=self._event_sequence)
        for event in events:
            expected = provenance_checksum(self._hashed_payload(event))
            if event.previous_hash != previous or event.event_hash != expected:
                return False
            previous = event.event_hash
        return True

    def assert_event_owner(self, *, event_id: str, step_id: str) -> None:
        """确认事件存在且由 ``step_id`` 生产或消费。

        本方法只用于恢复前校验 State 中的 ``provenanceRefs``。账本由存储层重建时
        已确认 runId、missionId 和哈希链，此处再把事件与步骤绑定，避免攻击者把同一
        运行内另一个步骤的事件挂到当前步骤上。
        """
        event = next(
            (
                item
                for item in [*self.productions, *self.consumptions, *self.interactions]
                if item.event_id == event_id
            ),
            None,
        )
        if event is None:
            raise ProvenanceIntegrityError(f"provenance event {event_id} does not exist")
        if isinstance(event, DataProductionEvent):
            owned = event.producer_step_id == step_id
        else:
            owned = event.consumer_step_id == step_id
        if not owned:
            raise ProvenanceIntegrityError(
                f"provenance event {event_id} does not belong to step {step_id}"
            )

    @classmethod
    def from_events(
        cls,
        *,
        run_id: str,
        mission_id: str,
        events: Iterable[dict[str, Any]],
        event_sink: Callable[[_Event], None] | None = None,
    ) -> "ProvenanceLedger":
        """从安全持久 JSON 重建账本，并在交给调用方前验证链条和归属。"""
        ledger = cls(run_id=run_id, mission_id=mission_id, event_sink=event_sink)
        parsed: list[_Event] = []
        for payload in events:
            try:
                event_id = str(payload.get("eventId") or "")
                if event_id.startswith("prod_"):
                    event: _Event = DataProductionEvent.model_validate(payload)
                elif event_id.startswith("cons_"):
                    event = DataConsumptionEvent.model_validate(payload)
                elif event_id.startswith("int_"):
                    event = RuntimeInteraction.model_validate(payload)
                else:
                    raise ProvenanceIntegrityError(f"unknown provenance event id: {event_id}")
            except ProvenanceIntegrityError:
                raise
            except Exception as exc:
                raise ProvenanceIntegrityError("provenance persisted event is malformed") from exc
            if event.run_id != run_id or event.mission_id != mission_id:
                raise ProvenanceIntegrityError("provenance event run or task ownership does not match")
            parsed.append(event)
        ordered = sorted(parsed, key=cls._event_sequence)
        if len({event.event_id for event in ordered}) != len(ordered):
            raise ProvenanceIntegrityError("provenance event identifiers are duplicated")
        for event in ordered:
            if isinstance(event, DataProductionEvent):
                ledger.productions.append(event)
            elif isinstance(event, DataConsumptionEvent):
                ledger.consumptions.append(event)
            else:
                ledger.interactions.append(event)
        ledger._seq = cls._event_sequence(ordered[-1]) if ordered else 0
        ledger._tail_hash = ordered[-1].event_hash if ordered else ""
        if not ledger.verify_integrity():
            raise ProvenanceIntegrityError("provenance integrity verification failed")
        return ledger

    def trace_events(self) -> list[dict[str, Any]]:
        """将账本事件投影为不含正文的持久 Trace 载荷。"""
        events = sorted(
            [*self.productions, *self.consumptions, *self.interactions],
            key=self._event_sequence,
        )
        return [self._trace_event(event) for event in events]

    @staticmethod
    def _event_sequence(event: _Event) -> int:
        """按账本分配的全局序号排序，不能按 prod/cons 前缀字典序排序。"""
        return int(event.event_id.rsplit("_", 1)[-1])

    @staticmethod
    def _trace_event(event: _Event) -> dict[str, Any]:
        """抽取审计需要的血缘元数据，禁止将 data/content 等正文进入投影。"""
        if isinstance(event, DataProductionEvent):
            payload = {
                "eventId": event.event_id,
                "producerStepId": event.producer_step_id,
                "fieldNames": list(event.field_names),
                "checksum": event.checksum,
                "tokenSize": event.token_size,
                "evidenceRefs": list(event.evidence_refs),
                "eventHash": event.event_hash,
            }
            event_type = "data_produced"
        elif isinstance(event, DataConsumptionEvent):
            payload = {
                "eventId": event.event_id,
                "consumerStepId": event.consumer_step_id,
                "producerStepIds": list(event.producer_step_ids),
                "producerEventIds": list(event.producer_event_ids),
                "fieldsByProducer": dict(event.fields_by_producer),
                "consumedFields": list(event.consumed_fields),
                "tokensDelivered": event.tokens_delivered,
                "tokensAvailable": event.tokens_available,
                "savingRatio": event.saving_ratio,
                "checksum": event.checksum,
                "contractStatus": event.contract_status,
                "eventHash": event.event_hash,
            }
            event_type = "data_consumed"
        else:
            payload = {
                "eventId": event.event_id,
                "interactionId": event.interaction_id,
                "producerStepIds": list(event.producer_step_ids),
                "consumerStepId": event.consumer_step_id,
                "fieldsByProducer": dict(event.fields_by_producer),
                "evidenceRefs": list(event.evidence_refs),
                "tokensDelivered": event.tokens_delivered,
                "tokensAvailable": event.tokens_available,
                "savingRatio": event.saving_ratio,
                "eventHash": event.event_hash,
            }
            event_type = "data_consumed"
        return {"eventType": event_type, "payload": payload}


__all__ = ["provenance_checksum", "DataProductionEvent", "DataConsumptionEvent", "RuntimeInteraction", "ProvenanceIntegrityError", "ProvenanceLedger"]
