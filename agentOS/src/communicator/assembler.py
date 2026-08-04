"""字段白名单上下文装配器。"""

from __future__ import annotations

from typing import Any, Mapping

from contracts.communication import MessageEnvelope

from .algorithms import select_fields
from .contracts import ContextPack, estimate_tokens, input_revision
from .provenance import ProvenanceLedger


def assemble(message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
    """将通用 JSON 负载封装为 contracts 定义的消息信封。"""
    return MessageEnvelope(messageId=message_id, topic=topic, sender=sender, recipient=recipient, payload=payload)


class ContextAssembler:
    """仅从 input_spec 声明的字段向下游投递，顺便汇集证据和血缘。"""
    def __init__(self, ledger: ProvenanceLedger | None = None) -> None:
        self.ledger = ledger or ProvenanceLedger()

    def assemble(self, *, run_id: str, step_id: str | None = None, input_spec: Mapping[str, Any] | None = None, upstream_outputs: Mapping[str, Mapping[str, Any]], objective: str = "", step_goal: str = "", task_id: str = "", attempt_id: str = "", binding_id: str = "", graph_version: int = 0, token_budget: int | None = None, step_node: object | None = None, **_: Any) -> ContextPack:
        """装配最小充分上下文；无字段合同即投递空 data，而不是隐式全量透传。"""
        if not self.ledger.run_id:
            self.ledger.run_id, self.ledger.task_id = run_id, task_id
        if step_node is not None:
            step_id = step_id or str(getattr(step_node, "node_id", ""))
            input_spec = input_spec or getattr(step_node, "input_spec", {})
            step_goal = step_goal or str(getattr(step_node, "goal", ""))
        spec = dict(input_spec or {})
        from_map = spec.get("from") if isinstance(spec.get("from"), Mapping) else {}
        field_list = spec.get("fields") if isinstance(spec.get("fields"), list) else []
        source_ids = list(from_map) if from_map else list(upstream_outputs)
        source_ids = [str(source) for source in source_ids if source in upstream_outputs]
        available = sum(estimate_tokens(upstream_outputs[source]) for source in source_ids)
        data: dict[str, Any] = {}; source_data: dict[str, dict[str, Any]] = {}; fields_by_producer: dict[str, list[str]] = {}
        for source in source_ids:
            output = upstream_outputs[source]
            allowed = list(from_map.get(source, [])) if from_map else list(field_list)
            chosen = select_fields(output, allowed, token_budget)
            for field in chosen:
                source_data.setdefault(source, {})[field] = output[field]
                data.setdefault(field, output[field])
            if chosen:
                fields_by_producer[source] = chosen
        evidence_refs = self._collect_evidence(source_ids, upstream_outputs)
        delivered = estimate_tokens(data)
        ratio = round(max(0.0, 1.0 - delivered / available), 4) if available else 0.0
        required = (spec.get("schema") or {}).get("required", []) if isinstance(spec.get("schema"), Mapping) else []
        missing = [str(field) for field in required if field not in data]
        pack = ContextPack(runId=run_id, stepId=step_id or "", objective=objective, stepGoal=step_goal, data=data, sourceData=source_data, evidenceRefs=evidence_refs, missingFields=missing, contractStatus="invalid" if missing else "valid", tokensDelivered=delivered, tokensAvailable=available, savingRatio=ratio, sourceStepIds=source_ids, graphVersion=graph_version, attemptId=attempt_id, bindingId=binding_id, inputRevision=input_revision(data))
        self.ledger.record_consumption(pack.step_id, source_ids, list(data), fields_by_producer=fields_by_producer, data=data, tokens_delivered=delivered, tokens_available=available, saving_ratio=ratio, contract_status=pack.contract_status)
        self.ledger.record_interaction(producer_step_ids=source_ids, consumer_step_id=pack.step_id, fields_by_producer=fields_by_producer, evidence_refs=evidence_refs, tokens_delivered=delivered, tokens_available=available, saving_ratio=ratio)
        return pack

    def record_production(self, step_id: str, output: dict[str, Any], *, agent_name: str = "", attempt: int = 1) -> None:
        self.ledger.record_production(step_id, output, estimate_tokens(output), agent_name=agent_name, attempt=attempt, evidence_refs=self._collect_evidence([step_id], {step_id: output}))

    @staticmethod
    def _collect_evidence(source_ids: list[str], outputs: Mapping[str, Mapping[str, Any]]) -> list[str]:
        refs: list[str] = []
        for source in source_ids:
            raw = outputs.get(source, {}).get("evidence_refs") or outputs.get(source, {}).get("evidenceRefs") or []
            for item in raw if isinstance(raw, list) else []:
                value = item if isinstance(item, str) else item.get("id") if isinstance(item, Mapping) else None
                if value and value not in refs: refs.append(str(value))
        return refs


__all__ = ["assemble", "ContextAssembler"]
