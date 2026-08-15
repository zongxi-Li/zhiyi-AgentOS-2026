"""ACG 工具部件的包边界；业务实现将在后续迁移。"""

__all__: list[str] = []
"""ACG 工具部件的公共入口。"""

from .service import ACGToolsService

__all__ = ["ACGToolsService"]
