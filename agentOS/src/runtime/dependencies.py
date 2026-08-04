"""运行时依赖的显式注册容器。"""

from typing import Any


class DependencyRegistry:
    """以名称管理应用层注入的依赖，避免部件自行连接外部系统。"""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def register(self, name: str, value: Any) -> None:
        self._values[name] = value

    def require(self, name: str) -> Any:
        if name not in self._values:
            raise RuntimeError(f"未注册运行时依赖：{name}")
        return self._values[name]
