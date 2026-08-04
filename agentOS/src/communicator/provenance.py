"""运行期通信血缘：生产、消费与交互事件的可验证账本。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def provenance_checksum(payload: Any) -> str:
    """以规范 JSON 计算哈希，使审计存储可以识别被篡改的投递内容。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _Event(BaseModel):
    """链式事件共有字段；previous_hash 使事件顺序也受完整性保护。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    event_id: str = Field(alias="eventId")
    run_id: str = Field(default="", alias="runId")
    task_id: str = Field(default="", alias="taskId")
    previous_hash: str = Field(default="", alias="previousHash")
    event_hash: str = Field(default="", alias="eventHash")
    created_at: datetime = Field(default_factory=_now, alias="createdAt")


class DataProductionEvent(_Event):
    producer_step_id: str = Field(alias="producerStepId")
    agent_name: str = Field(default="", alias="agentName")
    attempt: int = 1
    checksum: str = ""
    field_names: list[str] = Field(default_factory=list, alias="fieldNames")
    token_size: int = Field(default=0, alias="tokenSize")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")


class DataConsumptionEvent(_Event):
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
    interaction_id: str = Field(alias="interactionId")
    producer_step_ids: list[str] = Field(default_factory=list, alias="producerStepIds")
    consumer_step_id: str = Field(alias="consumerStepId")
    fields_by_producer: dict[str, list[str]] = Field(default_factory=dict, alias="fieldsByProducer")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")
    tokens_delivered: int = Field(default=0, alias="tokensDelivered")
    tokens_available: int = Field(default=0, alias="tokensAvailable")
    saving_ratio: float = Field(default=0.0, alias="savingRatio")


class ProvenanceLedger:
    """按运行隔离的生产/消费账本，记录每个字段跨步骤的流动。"""
    def __init__(self, *, run_id: str = "", task_id: str = "") -> None:
        self.run_id, self.task_id, self._seq, self._tail_hash = run_id, task_id, 0, ""
        self.productions: list[DataProductionEvent] = []
        self.consumptions: list[DataConsumptionEvent] = []
        self.interactions: list[RuntimeInteraction] = []

    def _seal(self, event: _Event) -> None:
        event.previous_hash = self._tail_hash
        event.event_hash = provenance_checksum(event.model_dump(by_alias=True, mode="json", exclude={"eventHash"}))
        self._tail_hash = event.event_hash

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:06d}"

    def record_production(self, step_id: str, output: dict[str, Any], token_size: int, *, agent_name: str = "", attempt: int = 1, evidence_refs: list[str] | None = None) -> DataProductionEvent:
        event = DataProductionEvent(eventId=self._next_id("prod"), runId=self.run_id, taskId=self.task_id, producerStepId=step_id, agentName=agent_name, attempt=attempt, checksum=provenance_checksum(output), fieldNames=sorted(output), tokenSize=token_size, evidenceRefs=list(dict.fromkeys(evidence_refs or [])))
        self._seal(event); self.productions.append(event)
        return event

    def record_consumption(self, step_id: str, producer_step_ids: list[str], consumed_fields: list[str], *, fields_by_producer: dict[str, list[str]], data: dict[str, Any], tokens_delivered: int, tokens_available: int, saving_ratio: float, contract_status: str = "valid") -> DataConsumptionEvent:
        producer_ids = list(dict.fromkeys(producer_step_ids))
        latest = {event.producer_step_id: event.event_id for event in self.productions}
        event = DataConsumptionEvent(eventId=self._next_id("cons"), runId=self.run_id, taskId=self.task_id, consumerStepId=step_id, producerStepIds=producer_ids, producerEventIds=[latest[source] for source in producer_ids if source in latest], fieldsByProducer=fields_by_producer, consumedFields=sorted(set(consumed_fields)), tokensDelivered=tokens_delivered, tokensAvailable=tokens_available, savingRatio=saving_ratio, checksum=provenance_checksum(data), contractStatus=contract_status)
        self._seal(event); self.consumptions.append(event)
        return event

    def record_interaction(self, *, producer_step_ids: list[str], consumer_step_id: str, fields_by_producer: dict[str, list[str]], evidence_refs: list[str], tokens_delivered: int, tokens_available: int, saving_ratio: float) -> RuntimeInteraction:
        event_id = self._next_id("int")
        event = RuntimeInteraction(eventId=event_id, interactionId=event_id, runId=self.run_id, taskId=self.task_id, producerStepIds=list(dict.fromkeys(producer_step_ids)), consumerStepId=consumer_step_id, fieldsByProducer=fields_by_producer, evidenceRefs=list(dict.fromkeys(evidence_refs)), tokensDelivered=tokens_delivered, tokensAvailable=tokens_available, savingRatio=saving_ratio)
        self._seal(event); self.interactions.append(event)
        return event

    def verify_integrity(self) -> bool:
        previous = ""
        events = sorted([*self.productions, *self.consumptions, *self.interactions], key=lambda item: item.event_id)
        for event in events:
            expected = provenance_checksum(event.model_dump(by_alias=True, mode="json", exclude={"eventHash"}))
            if event.previous_hash != previous or event.event_hash != expected:
                return False
            previous = event.event_hash
        return True


__all__ = ["provenance_checksum", "DataProductionEvent", "DataConsumptionEvent", "RuntimeInteraction", "ProvenanceLedger"]
