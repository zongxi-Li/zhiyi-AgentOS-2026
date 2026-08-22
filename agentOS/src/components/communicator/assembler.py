"""字段白名单上下文装配器。"""

from __future__ import annotations

from typing import Any, Mapping

from contracts.communication import MessageEnvelope

from .algorithms import select_fields
from .contracts import ContextPack, estimate_tokens, input_revision
from .provenance import ProvenanceLedger


def assemble(message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
    """将通用 JSON 负载封装为通信合同规定的消息信封。

    输入标识、主题、发送方及可选接收方原样交给 ``MessageEnvelope`` 校验；返回
    新信封且不执行网络投递。合同字段不合法时由模型校验错误上抛，复杂度 O(1)。
    """
    return MessageEnvelope(messageId=message_id, topic=topic, sender=sender, recipient=recipient, payload=payload)


class ContextAssembler:
    """按输入合同白名单装配下游上下文，并记录通信血缘。

    实例持有一个可注入账本；首个装配调用会设置其运行标识，之后应仅服务同一
    运行。该类不访问网络，账本并发写入与跨运行复用由调用方同步。
    """
    def __init__(self, ledger: ProvenanceLedger | None = None) -> None:
        self.ledger = ledger or ProvenanceLedger()

    def assemble(self, *, run_id: str, step_id: str | None = None, input_spec: Mapping[str, Any] | None = None, upstream_outputs: Mapping[str, Mapping[str, Any]], objective: str = "", step_goal: str = "", mission_id: str = "", attempt_id: str = "", binding_id: str = "", graph_version: int = 0, token_budget: int | None = None, step_node: object | None = None, operation_id: str = "", **_: Any) -> ContextPack:
        """从上游输出装配满足 ``input_spec`` 的最小充分 ``ContextPack``。

        只投递白名单字段并按预算选择，缺少必填字段会使返回包标记为 invalid；
        同时向账本追加消费和交互事件。无字段合同产生空数据而非全量透传。设
        字段数为 n，主要排序成本为 O(n log n)，输入映射不被修改。
        """
        if not self.ledger.run_id:
            self.ledger.run_id, self.ledger.mission_id = run_id, mission_id
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
        # 一个节点提交会产生两类不同事实：字段消费与上下文交互。它们各自从同一
        # commitId 派生角色键，重试时能分别复用，又不会被误判为彼此冲突的重复事件。
        consumption_operation = f"{operation_id}:consume" if operation_id else ""
        interaction_operation = f"{operation_id}:interact" if operation_id else ""
        self.ledger.record_consumption(pack.step_id, source_ids, list(data), fields_by_producer=fields_by_producer, data=data, tokens_delivered=delivered, tokens_available=available, saving_ratio=ratio, contract_status=pack.contract_status, operation_id=consumption_operation)
        self.ledger.record_interaction(producer_step_ids=source_ids, consumer_step_id=pack.step_id, fields_by_producer=fields_by_producer, evidence_refs=evidence_refs, tokens_delivered=delivered, tokens_available=available, saving_ratio=ratio, operation_id=interaction_operation)
        return pack

    def record_production(self, step_id: str, output: dict[str, Any], *, agent_name: str = "", attempt: int = 1, operation_id: str = "") -> None:
        """把步骤 ``output`` 的字段、Token 与证据血缘登记到当前账本。

        该方法不复制或变更输出，仅追加一条生产事件；证据从约定字段中提取。
        账本错误会直接上抛，处理复杂度取决于输出序列化与字段数，为 O(n)。
        """
        self.ledger.record_production(step_id, output, estimate_tokens(output), agent_name=agent_name, attempt=attempt, evidence_refs=self._collect_evidence([step_id], {step_id: output}), operation_id=operation_id)

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
