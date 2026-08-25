"""ACG 内部通信拓扑、字段许可和预算声明。

Manifest 由执行编译器或运行时装配层持有，不进入 ``contracts/``。它不保存输出正文，
只说明哪个步骤可以读取哪个生产步骤的哪类字段，以及该通道允许使用的最大预算。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CommunicationRule:
    """一条 producer -> consumer 的最小通信许可。"""

    producer_step_id: str
    consumer_step_id: str
    allowed_fields: tuple[str, ...]
    channel: str
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.producer_step_id or not self.consumer_step_id or not self.channel:
            raise ValueError("communication rule identifiers must not be empty")
        if self.max_tokens is not None and self.max_tokens < 0:
            raise ValueError("communication rule max_tokens must not be negative")
        if len(set(self.allowed_fields)) != len(self.allowed_fields):
            raise ValueError("communication rule allowed_fields must be unique")


class CommunicationManifest:
    """一个 run 的不可变通信许可和三级预算初始值。"""

    def __init__(
        self,
        *,
        run_id: str,
        rules: tuple[CommunicationRule, ...],
        run_budget: int | None = None,
        step_budgets: Mapping[str, int] | None = None,
        channel_budgets: Mapping[str, int] | None = None,
    ) -> None:
        if not run_id:
            raise ValueError("communication manifest run_id must not be empty")
        if run_budget is not None and run_budget < 0:
            raise ValueError("communication manifest run_budget must not be negative")
        normalized_steps = dict(step_budgets or {})
        normalized_channels = dict(channel_budgets or {})
        if any(value < 0 for value in normalized_steps.values()):
            raise ValueError("communication step budgets must not be negative")
        if any(value < 0 for value in normalized_channels.values()):
            raise ValueError("communication channel budgets must not be negative")
        keys = [(rule.producer_step_id, rule.consumer_step_id) for rule in rules]
        if len(set(keys)) != len(keys):
            raise ValueError("communication manifest contains duplicate topology rules")
        self.run_id = run_id
        self.rules = tuple(rules)
        self.run_budget = run_budget
        self.step_budgets = normalized_steps
        self.channel_budgets = normalized_channels

    def rules_for_consumer(self, consumer_step_id: str) -> tuple[CommunicationRule, ...]:
        """返回下游步骤可尝试验证的入边；正文读取仍由 Broker 执行。"""
        return tuple(rule for rule in self.rules if rule.consumer_step_id == consumer_step_id)


__all__ = ["CommunicationManifest", "CommunicationRule"]
