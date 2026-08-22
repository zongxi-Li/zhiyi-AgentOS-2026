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
        self.restore_usage(usage or {})

    async def read_reference(
        self,
        *,
        run_id: str,
        consumer_step_id: str,
        output_ref: str,
        requested_fields: Iterable[str],
        max_tokens: int,
        reason: str,
    ) -> ContextPack:
        """读取一个经拓扑与预算许可的输出引用，并返回字段裁剪后的 ContextPack。

        ``reason`` 仅供当前调用边界诊断，不会写入事件、Trace 或持久化状态。请求字段
        为空时代表“只要该边已授权的全部字段”；它不会绕过 Manifest 的字段许可。
        """
        if run_id != self.manifest.run_id:
            raise CommunicationAccessError("RUN_DENIED", "communication run does not match manifest")
        if max_tokens < 0:
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
        if tokens > max_tokens or tokens > rule.max_tokens:
            raise EntropyBudgetExceededError("communication read exceeds request or rule token limit")
        self._reserve(consumer_step_id=consumer_step_id, channel=rule.channel, tokens=tokens)
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
        self._events.append(
            {
                "type": "communication_read",
                "runId": run_id,
                "consumerStepId": consumer_step_id,
                "producerStepId": rule.producer_step_id,
                "outputRef": output_ref,
                "fields": list(data),
                "tokens": tokens,
                "channel": rule.channel,
            }
        )
        return pack

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

    def usage_snapshot(self) -> dict[str, Any]:
        """返回可进入 State/checkpoint 的通信消耗计数，不包含引用或正文。"""
        return {
            "run": self._run_used,
            "steps": dict(self._step_used),
            "channels": dict(self._channel_used),
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

    @staticmethod
    def _normalize_usage(values: Mapping[str, Any]) -> dict[str, int]:
        normalized: dict[str, int] = {}
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

    def _reserve(self, *, consumer_step_id: str, channel: str, tokens: int) -> None:
        """先检查三级剩余额度，再一次性扣减，失败请求不会部分计费。"""
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

    @staticmethod
    def _saving_ratio(delivered: int, available: int) -> float:
        """用已投递和完整输出估算节省比例，空输出不产生虚假收益。"""
        return round(max(0.0, 1.0 - delivered / available), 4) if available else 0.0


__all__ = ["CommunicationAccessError", "CommunicationBroker", "EntropyBudgetExceededError"]
