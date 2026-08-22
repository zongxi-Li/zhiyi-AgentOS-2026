"""New ACG Runtime Foundation 公共入口。"""

from .context import ExecutionContext
from contracts.planning import TaskImplementationBinding, TaskPlan, PlannedTask, TaskPlanPatch
from .planner_bridge import PlannerIdentityBridge
from .queries import IdentityQueryService
from .runner import AcgIdentityLifecycleService
from .identity_projection import IdentityProjectionBridge
from .reconciliation import IdentityProjectionReconciler, IdentityReconciliationReport

__all__ = [
    "AcgIdentityLifecycleService",
    "ExecutionContext",
    "IdentityQueryService",
    "IdentityProjectionReconciler",
    "IdentityReconciliationReport",
    "PlannerIdentityBridge",
    "TaskImplementationBinding",
    "TaskPlan",
    "PlannedTask",
    "TaskPlanPatch",
    "IdentityProjectionBridge",
]
