"""恢复计划创建器。"""

from contracts.recovery import FailureEvent, FailureType, RecoveryAction, RecoveryPlan


def plan_recovery(event: FailureEvent) -> RecoveryPlan:
    """根据失败的重试语义生成最小、合同合法的恢复计划。"""
    if event.failure_type in {FailureType.CAPACITY, FailureType.LEASE_EXPIRED}:
        strategy = RecoveryAction.REBIND
    elif event.failure_type in {FailureType.POLICY, FailureType.CONTROL}:
        strategy = RecoveryAction.REVIEW
    elif event.retryable:
        strategy = RecoveryAction.RETRY
    else:
        strategy = RecoveryAction.ABORT
    return RecoveryPlan(
        planId=f"recovery-{event.failure_id}",
        failureId=event.failure_id,
        strategy=strategy,
        steps=[f"{strategy.value}:{event.subject_ref}"],
    )
