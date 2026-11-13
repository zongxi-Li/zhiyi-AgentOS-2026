"""ACG 运行期受控按需读取 Broker。

下游 Agent 不会直接取得上游输出集合。它只可经本模块用 outputRef 发起读取；Broker
依次验证 run、来源步骤、拓扑、字段许可、请求上限和三级预算，随后才从 Value Store
读取正文。State、checkpoint 与 Broker 事件始终只保存引用和统计，不复制正文。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Mapping, Protocol

from .contracts import ContextPack, estimate_tokens, input_revision
from .manifest import CommunicationManifest, CommunicationRule


class CommunicationAccessError(PermissionError):
    """运行期通信许可不足时的稳定、无正文错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EntropyBudgetExceededError(ValueError):
    """run、step 或 channel 预算不能承载本次受控读取时抛出。"""

    code = "COMMUNICATION_BUDGET_EXCEEDED"


class ExecutionValueReader(Protocol):
    """Broker 所需的最小值仓库接口，避免通信器反向依赖 executor 包入口。"""

    def assert_reference(self, *, kind: str, run_id: str, step_id: str, reference: str) -> None:
        """验证引用归属，不返回正文。"""

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        """在引用通过校验后读取受控输出正文。"""


class CommunicationBroker:
    """执行 Manifest 的唯一正文读取入口，并维护当前进程的预算消耗。"""

    def __init__(
        self,
        *,
        manifest: CommunicationManifest,
        value_store: ExecutionValueReader,
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        self.manifest = manifest
        self.value_store = value_store
        self._run_used = 0
        self._step_used: dict[str, int] = {}
        self._channel_used: dict[str, int] = {}
        self._events: list[dict[str, Any]] = []
        self._event_operations: set[str] = set()
        self._operations: dict[str, dict[str, Any]] = {}
        self._supplemental_used: dict[str, int] = {}
        self.restore_usage(usage or {})

    async def read_reference(
        self,
        *,
        run_id: str,
        consumer_step_id: str,
        output_ref: str,
        requested_fields: Iterable[str],
        max_tokens: int | None,
        reason: str,
        operation_id: str = "",
        supplemental_limit: int | None = None,
    ) -> ContextPack:
        """读取一个经拓扑与预算许可的输出引用，并返回字段裁剪后的 ContextPack。

        ``reason`` 仅供当前调用边界诊断，不会写入事件、Trace 或持久化状态。请求字段
        为空时代表“只要该边已授权的全部字段”；它不会绕过 Manifest 的字段许可。
        """
        if run_id != self.manifest.run_id:
            raise CommunicationAccessError("RUN_DENIED", "communication run does not match manifest")
        if max_tokens is not None and max_tokens < 0:
            raise ValueError("max_tokens must not be negative")
        requested = tuple(dict.fromkeys(str(field) for field in requested_fields if str(field)))
        rule = self._resolve_rule(
            run_id=run_id,
            consumer_step_id=consumer_step_id,
            output_ref=output_ref,
        )
        fields = requested or rule.allowed_fields
        denied = set(fields) - set(rule.allowed_fields)
        if denied:
            raise CommunicationAccessError("FIELD_DENIED", "requested fields are not permitted by communication rule")
        # 来源步骤归属已在 _resolve_rule 无正文验证；通过全部权限检查后才读取该输出。
        output = self.value_store.get_output(run_id=run_id, output_ref=output_ref)
        data = {field: output[field] for field in fields if field in output}
        evidence_refs: list[str] = []
        raw_evidence = data.get("evidence_refs") or data.get("evidenceRefs") or []
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                value = (
                    item
                    if isinstance(item, str)
                    else item.get("id")
                    if isinstance(item, Mapping)
                    else None
                )
                if value and str(value) not in evidence_refs:
                    evidence_refs.append(str(value))
        tokens = estimate_tokens(data)
        if ((max_tokens is not None and tokens > max_tokens)
                or (rule.max_tokens is not None and tokens > rule.max_tokens)):
            raise EntropyBudgetExceededError("communication read exceeds request or rule token limit")
        self._reserve(consumer_step_id=consumer_step_id, channel=rule.channel, tokens=tokens,
                      operation_id=operation_id, supplemental_limit=supplemental_limit,
                      fingerprint=input_revision([output_ref, list(fields), data, max_tokens, supplemental_limit]))
        pack = ContextPack(
            runId=run_id,
            stepId=consumer_step_id,
            data=data,
            sourceData={rule.producer_step_id: dict(data)},
            evidenceRefs=evidence_refs,
            tokensDelivered=tokens,
            tokensAvailable=estimate_tokens(output),
            savingRatio=self._saving_ratio(tokens, estimate_tokens(output)),
            sourceStepIds=[rule.producer_step_id],
            inputRevision=input_revision(data),
        )
        self._append_event(
            {
                "type": "communication_read",
                "runId": run_id,
                "consumerStepId": consumer_step_id,
                "producerStepId": rule.producer_step_id,
                "outputRef": output_ref,
                "fields": list(data),
                "tokens": tokens,
                "channel": rule.channel,
                **({"operationId": operation_id, "readKind": "fields", "readPhase": "supplemental" if supplemental_limit is not None else "prefetch"}
                   if operation_id else {}),
            }, operation_id=operation_id,
        )
        return pack

    async def read_reference_page(
        self, *, run_id: str, consumer_step_id: str, output_ref: str,
        requested_fields: Iterable[str], cursor: str | None,
        page_tokens: int, reason: str,
        operation_id: str = "", supplemental_limit: int | None = None,
    ) -> tuple[ContextPack, str | None]:
        """Page one authorized large field without deleting any remaining content.

        The cursor identifies a field and an item/character offset.  Callers may lower
        ``page_tokens`` reactively when an API reports context pressure; traversing all
        returned cursors reconstructs the complete authorized value.
        """
        if page_tokens < 1:
            raise ValueError("page_tokens must be positive")
        if run_id != self.manifest.run_id:
            raise CommunicationAccessError("RUN_DENIED", "communication run does not match manifest")
        requested = tuple(dict.fromkeys(str(field) for field in requested_fields if str(field)))
        rule = self._resolve_rule(
            run_id=run_id, consumer_step_id=consumer_step_id, output_ref=output_ref
        )
        fields = requested or rule.allowed_fields
        if set(fields) - set(rule.allowed_fields):
            raise CommunicationAccessError("FIELD_DENIED", "requested fields are not permitted by communication rule")
        try:
            field_index, offset = (int(item) for item in (cursor or "0:0").split(":", 1))
        except (TypeError, ValueError) as exc:
            raise CommunicationAccessError("CURSOR_INVALID", "communication cursor is invalid") from exc
        if field_index < 0 or field_index >= len(fields) or offset < 0:
            raise CommunicationAccessError("CURSOR_INVALID", "communication cursor is invalid")

        output = self.value_store.get_output(run_id=run_id, output_ref=output_ref)
        field = fields[field_index]
        value = output.get(field)
        # Account for the field envelope too. Never return a first oversized
        # item merely to make progress: it would silently bypass the page cap.
        overhead = estimate_tokens({field: None}) + 2
        if page_tokens <= overhead:
            raise EntropyBudgetExceededError("page budget cannot hold the field envelope")
        page_value, next_offset = self._slice_value(value, offset=offset, page_tokens=page_tokens - overhead)
        next_cursor = (
            f"{field_index}:{next_offset}"
            if next_offset is not None
            else f"{field_index + 1}:0"
            if field_index + 1 < len(fields)
            else None
        )
        data = {field: page_value}
        tokens = estimate_tokens(data)
        if tokens > page_tokens:
            raise EntropyBudgetExceededError("page item exceeds budget; increase page size within the read limit")
        if rule.max_tokens is not None and tokens > rule.max_tokens:
            raise EntropyBudgetExceededError("communication page exceeds rule token limit")
        self._reserve(consumer_step_id=consumer_step_id, channel=rule.channel, tokens=tokens,
                      operation_id=operation_id, supplemental_limit=supplemental_limit,
                      fingerprint=input_revision([output_ref, list(fields), cursor, page_tokens, data, supplemental_limit]))
        raw_evidence = page_value if field in {"evidence_refs", "evidenceRefs"} else []
        evidence_refs = list(dict.fromkeys(
            str(item) for item in raw_evidence if str(item).strip()
        )) if isinstance(raw_evidence, list) else []
        pack = ContextPack(
            runId=run_id, stepId=consumer_step_id, data=data,
            sourceData={rule.producer_step_id: dict(data)}, evidenceRefs=evidence_refs,
            # Paging defers content; it does not remove it. Comparing every page
            # with the entire field would manufacture savings on every page.
            tokensDelivered=tokens, tokensAvailable=tokens, savingRatio=0.0,
            sourceStepIds=[rule.producer_step_id], inputRevision=input_revision(data),
        )
        self._append_event({
            "type": "communication_page_read", "runId": run_id,
            "consumerStepId": consumer_step_id, "producerStepId": rule.producer_step_id,
            "outputRef": output_ref, "fields": [field], "tokens": tokens,
            "channel": rule.channel, "cursor": cursor, "nextCursor": next_cursor,
            **({"operationId": operation_id, "readKind": "page", "sourceTokensAvailable": estimate_tokens({field: value}),
                "readPhase": "supplemental" if supplemental_limit is not None else "prefetch"}
               if operation_id else {}),
        }, operation_id=operation_id)
        return pack, next_cursor

    @staticmethod
    def _slice_value(value: Any, *, offset: int, page_tokens: int) -> tuple[Any, int | None]:
        """Return a non-empty bounded slice and the next logical offset."""
        if isinstance(value, str):
            if offset > len(value):
                raise CommunicationAccessError("CURSOR_INVALID", "cursor exceeds field size")
            # JSON escaping can make a character cost more than one token.
            low, high = 0, len(value) - offset
            while low < high:
                mid = (low + high + 1) // 2
                if estimate_tokens([value[offset:offset + mid]]) <= page_tokens:
                    low = mid
                else:
                    high = mid - 1
            width = max(1, low)
            page = value[offset:offset + width]
            following = offset + len(page)
            return page, following if following < len(value) else None
        if isinstance(value, list):
            if offset > len(value):
                raise CommunicationAccessError("CURSOR_INVALID", "cursor exceeds field size")
            page: list[Any] = []
            index = offset
            while index < len(value):
                candidate = [*page, value[index]]
                if page and estimate_tokens(candidate) > page_tokens:
                    break
                page = candidate
                index += 1
            return page, index if index < len(value) else None
        if isinstance(value, Mapping):
            entries = list(value.items())
            if offset > len(entries):
                raise CommunicationAccessError("CURSOR_INVALID", "cursor exceeds field size")
            page: dict[str, Any] = {}
            index = offset
            while index < len(entries):
                key, item = entries[index]
                candidate = {**page, str(key): item}
                if page and estimate_tokens(candidate) > page_tokens:
                    break
                page = candidate
                index += 1
            return page, index if index < len(entries) else None
        if offset > 0:
            return None, None
        return value, None

    def drain_events(self, *, consumer_step_id: str | None = None) -> list[dict[str, Any]]:
        """领取无正文读取审计事件；返回后清空私有缓冲避免后续步骤重复投影。"""
        events = [
            event for event in self._events
            if consumer_step_id is None or event["consumerStepId"] == consumer_step_id
        ]
        if consumer_step_id is None:
            self._events.clear()
        else:
            self._events = [
                event for event in self._events if event["consumerStepId"] != consumer_step_id
            ]
        return events

    def _append_event(self, event: dict[str, Any], *, operation_id: str) -> None:
        if not operation_id or operation_id not in self._event_operations:
            self._events.append(event)
            if operation_id:
                self._event_operations.add(operation_id)

    def usage_snapshot(self) -> dict[str, Any]:
        """返回可进入 State/checkpoint 的通信消耗计数，不包含引用或正文。"""
        return {
            "run": self._run_used,
            "steps": dict(self._step_used),
            "channels": dict(self._channel_used),
            **({"readOperations": {key: dict(value) for key, value in self._operations.items()}, "supplemental": dict(self._supplemental_used)}
               if self._operations or self._supplemental_used else {}),
        }

    def restore_usage(self, usage: Mapping[str, Any]) -> None:
        """从检查点恢复已消费预算；非法值明确拒绝而不是重置额度。"""
        run_used = usage.get("run", 0)
        steps = usage.get("steps", {})
        channels = usage.get("channels", {})
        if (
            not isinstance(run_used, int)
            or isinstance(run_used, bool)
            or run_used < 0
            or not isinstance(steps, Mapping)
            or not isinstance(channels, Mapping)
        ):
            raise ValueError("communication usage is invalid")
        normalized_steps = self._normalize_usage(steps)
        normalized_channels = self._normalize_usage(channels)
        self._run_used = run_used
        self._step_used = normalized_steps
        self._channel_used = normalized_channels
        self._supplemental_used = self._normalize_usage(usage.get("supplemental", {}))
        operations = usage.get("readOperations", {})
        if not isinstance(operations, Mapping):
            raise ValueError("communication operations are invalid")
        for key, record in operations.items():
            if (not isinstance(key, str) or not isinstance(record, Mapping)
                    or set(record) != {"fingerprint"} or not isinstance(record["fingerprint"], str)):
                raise ValueError("communication operation receipt is invalid")
        self._operations = {key: dict(record) for key, record in operations.items()}

    @staticmethod
    def _normalize_usage(values: Mapping[str, Any]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        if not isinstance(values, Mapping):
            raise ValueError("communication usage counters must be a mapping")
        for key, value in values.items():
            if not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("communication usage counters are invalid")
            normalized[key] = value
        return normalized

    def _resolve_rule(
        self,
        *,
        run_id: str,
        consumer_step_id: str,
        output_ref: str,
    ) -> CommunicationRule:
        """在所有入边上验证引用归属，成功时返回唯一的生产者许可。"""
        candidates = self.manifest.rules_for_consumer(consumer_step_id)
        for rule in candidates:
            try:
                self.value_store.assert_reference(
                    kind="output",
                    run_id=run_id,
                    step_id=rule.producer_step_id,
                    reference=output_ref,
                )
            except ValueError:
                continue
            return rule
        raise CommunicationAccessError("TOPOLOGY_DENIED", "output reference has no permitted topology edge")

    def _reserve(self, *, consumer_step_id: str, channel: str, tokens: int,
                 operation_id: str = "", fingerprint: str = "", supplemental_limit: int | None = None) -> None:
        """先检查三级剩余额度，再一次性扣减，失败请求不会部分计费。"""
        if operation_id and operation_id in self._operations:
            if self._operations[operation_id]["fingerprint"] != fingerprint:
                raise CommunicationAccessError("READ_OPERATION_CONFLICT", "read operation changed during replay")
            return
        supplemental_next = self._supplemental_used.get(consumer_step_id, 0) + tokens
        if supplemental_limit is not None and supplemental_next > supplemental_limit:
            raise EntropyBudgetExceededError("supplemental step budget exceeded")
        run_next = self._run_used + tokens
        step_next = self._step_used.get(consumer_step_id, 0) + tokens
        channel_next = self._channel_used.get(channel, 0) + tokens
        if self.manifest.run_budget is not None and run_next > self.manifest.run_budget:
            raise EntropyBudgetExceededError("communication run budget exceeded")
        step_budget = self.manifest.step_budgets.get(consumer_step_id)
        if step_budget is not None and step_next > step_budget:
            raise EntropyBudgetExceededError("communication step budget exceeded")
        channel_budget = self.manifest.channel_budgets.get(channel)
        if channel_budget is not None and channel_next > channel_budget:
            raise EntropyBudgetExceededError("communication channel budget exceeded")
        self._run_used = run_next
        self._step_used[consumer_step_id] = step_next
        self._channel_used[channel] = channel_next
        if supplemental_limit is not None:
            self._supplemental_used[consumer_step_id] = supplemental_next
        if operation_id:
            self._operations[operation_id] = {"fingerprint": fingerprint}

    def describe_reference(self, *, run_id: str, consumer_step_id: str, output_ref: str) -> dict[str, Any]:
        """Expose sizes of permitted fields only; never expose output references or text."""
        if run_id != self.manifest.run_id:
            raise CommunicationAccessError("RUN_DENIED", "communication run does not match manifest")
        rule = self._resolve_rule(run_id=run_id, consumer_step_id=consumer_step_id, output_ref=output_ref)
        output = self.value_store.get_output(run_id=run_id, output_ref=output_ref)
        return {"producerStepId": rule.producer_step_id, "fields": [
            {"name": field, "present": field in output,
             "estimatedTokens": estimate_tokens({field: output[field]}) if field in output else 0,
             "valueType": type(output[field]).__name__ if field in output else "missing"}
            for field in rule.allowed_fields]}

    @staticmethod
    def _saving_ratio(delivered: int, available: int) -> float:
        """用已投递和完整输出估算节省比例，空输出不产生虚假收益。"""
        return round(max(0.0, 1.0 - delivered / available), 4) if available else 0.0


__all__ = ["CommunicationAccessError", "CommunicationBroker", "EntropyBudgetExceededError"]
