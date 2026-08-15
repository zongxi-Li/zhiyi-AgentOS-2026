"""恢复部件的公共 Facade。"""

from contracts.recovery import FailureEvent, RecoveryPlan

from .planner import plan_recovery
from .recipes import RecoveryRecipeRegistry
from .validator import valid_recovery_plan


class RecoveryService:
    """将失败事实转换为经过本地校验的恢复计划。"""

    def __init__(self, recipe_registry: RecoveryRecipeRegistry | None = None) -> None:
        self.recipe_registry = recipe_registry or RecoveryRecipeRegistry()

    def select_recipe(
        self,
        failure: FailureEvent,
        *,
        application_counts: dict[str, int] | None = None,
    ):
        """Select a declarative recipe without executing or mutating a graph."""
        return self.recipe_registry.match(failure, application_counts=application_counts)

    def propose(self, failure: FailureEvent) -> RecoveryPlan:
        """生成计划；若本地不合法则明确中止而不是执行不完整恢复。"""
        plan = plan_recovery(failure)
        if not valid_recovery_plan(plan):
            raise ValueError("恢复计划未满足运行前校验")
        return plan
