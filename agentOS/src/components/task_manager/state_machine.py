"""AgentOS Core 的 state_machine 模块，提供运行时控制、状态、Trace、审核或治理能力。"""


from enum import Enum
from typing import TypeVar

from contracts.workflow import StepStatus, WorkflowStatus

StatusT = TypeVar("StatusT", WorkflowStatus, StepStatus)


class InvalidStateTransition(ValueError):
    """工作流或步骤尝试非法状态流转时抛出。"""


class StateMachine:
    """工作流运行和步骤共享的状态机。"""

    # 状态转移是有限状态机，单次查询与校验均为 O(1)，不随任务数量增长。
    _transitions = {
        "pending": {"planning", "running", "failed", "cancelled", "superseded", "skipped_by_condition"},
        "planning": {"running", "failed", "cancelled", "superseded"},
        "running": {"waiting_review", "retrying", "failed", "completed", "cancelled", "superseded"},
        "waiting_review": {"running", "retrying", "failed", "completed", "cancelled", "superseded"},
        "retrying": {"running", "failed", "cancelled", "superseded"},
        "failed": {"retrying", "cancelled"},
        "completed": set(),
        "cancelled": set(),
        "superseded": set(),
        "skipped_by_condition": set(),
    }

    def can_transition(self, current: Enum, target: Enum) -> bool:
        """判断状态迁移是否被有限状态表允许；查询复杂度 ``O(1)``，同态迁移允许。"""
        if current == target:
            return True
        return target.value in self._transitions.get(current.value, set())

    def transition(self, current: StatusT, target: StatusT) -> StatusT:
        """校验并返回目标状态；非法迁移不修改输入且抛出 ``InvalidStateTransition``。"""
        if not self.can_transition(current, target):
            raise InvalidStateTransition(f"illegal transition: {current.value} -> {target.value}")
        return target
