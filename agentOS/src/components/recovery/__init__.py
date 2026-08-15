"""恢复部件的包边界；业务实现将在后续迁移。"""

__all__: list[str] = []


"""恢复部件的公共入口。"""

from .contract_repair import repair_payload
from .recipes import RecoveryRecipeRegistry
from .service import RecoveryService

__all__ = ["RecoveryRecipeRegistry", "RecoveryService", "repair_payload"]
