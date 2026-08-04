"""通信协调部件的包边界；业务实现将在后续迁移。"""

__all__: list[str] = []
"""通信部件的公共入口。"""

from .service import CommunicatorService

__all__ = ["CommunicatorService"]
