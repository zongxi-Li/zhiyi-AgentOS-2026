"""执行部件的包边界；业务实现将在后续迁移。"""

__all__: list[str] = []
"""执行部件的公共入口。"""

from .service import ExecutorService

__all__ = ["ExecutorService"]
