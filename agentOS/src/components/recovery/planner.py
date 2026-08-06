"""恢复计划创建器。"""

from contracts.recovery import FailureEvent, RecoveryPlan


def plan_recovery(event: FailureEvent) -> RecoveryPlan:
    """根据失败的重试语义生成最小、合同合法的恢复计划。"""
    strategy = "retry" if event.retryable else "abort"
    return RecoveryPlan(planId=f"recovery-{event.failure_id}", failureId=event.failure_id, strategy=strategy, steps=[f"{strategy}:{event.subject_ref}"])
