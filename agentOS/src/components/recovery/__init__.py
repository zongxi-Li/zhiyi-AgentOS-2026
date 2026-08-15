"""恢复部件的包边界；业务实现将在后续迁移。"""

__all__: list[str] = []


"""恢复部件的公共入口。"""

from .service import RecoveryService

__all__ = ["RecoveryService"]
