"""恢复计划的运行前校验。"""

from contracts.recovery import RecoveryPlan


def valid_recovery_plan(plan: RecoveryPlan) -> bool:
    """图补丁策略必须附带补丁引用，其他策略允许空步骤列表。"""
    return plan.strategy != "patch_graph" or plan.graph_patch is not None
