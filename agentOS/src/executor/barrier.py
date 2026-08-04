"""并发阶段结果屏障：原子合并并拒绝迟到结果。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dispatcher import StepExecutionOutcome
from .graph import RuntimeGraph, RuntimeNodeStatus


def barrier_satisfied(expected: set[str], completed: set[str]) -> bool:
    """所有预期节点完成时才允许下一个执行阶段开始。"""
    return expected <= completed


@dataclass
class ResultBarrier:
    """收集一个批次的 detached outcome，完整后一次性写入图副本。

    ``attempt_id`` 与调度图版本双重匹配，图被恢复流程推进后到达的结果不会
    覆盖较新的状态。调用者持有运行锁时调用 ``merge``，即可获得单写原子性。
    """

    expected_attempt_ids: set[str]
    outcomes: dict[str, StepExecutionOutcome] = field(default_factory=dict)

    def record(self, outcome: StepExecutionOutcome) -> bool:
        if outcome.attempt_id not in self.expected_attempt_ids or outcome.attempt_id in self.outcomes:
            return False
        self.outcomes[outcome.attempt_id] = outcome
        return True

    @property
    def satisfied(self) -> bool:
        return self.expected_attempt_ids <= set(self.outcomes)

    def merge(self, graph: RuntimeGraph) -> tuple[list[StepExecutionOutcome], list[StepExecutionOutcome]]:
        """返回 ``(accepted, rejected)``；不完整批次不修改图。"""
        if not self.satisfied:
            return [], []
        accepted: list[StepExecutionOutcome] = []
        rejected: list[StepExecutionOutcome] = []
        # 先验证全部结果；任一陈旧结果存在时，仍逐个拒绝而不部分覆盖同一节点。
        for outcome in sorted(self.outcomes.values(), key=lambda item: item.runtime_node_id):
            try:
                node = graph.get_node(outcome.runtime_node_id)
            except KeyError:
                rejected.append(outcome); continue
            attempt = node.attempts[-1] if node.attempts else None
            if (outcome.graph_id != graph.graph_id or outcome.scheduled_graph_version != graph.graph_version
                    or attempt is None or attempt.attempt_id != outcome.attempt_id):
                rejected.append(outcome); continue
            accepted.append(outcome)
        for outcome in accepted:
            node = graph.get_node(outcome.runtime_node_id)
            attempt = node.attempts[-1]
            attempt.status = RuntimeNodeStatus(outcome.status)
            attempt.ended_at = outcome.ended_at
            attempt.resolved_input = dict(outcome.resolved_input)
            attempt.output = dict(outcome.output)
            attempt.error = outcome.error
            node.status = RuntimeNodeStatus(outcome.status)
            node.output = dict(outcome.output)
            node.output_version += 1 if outcome.output else 0
            node.error = outcome.error
        return accepted, rejected


__all__ = ["ResultBarrier", "barrier_satisfied"]
