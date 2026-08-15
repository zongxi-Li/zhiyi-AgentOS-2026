"""应用启动的部件装配入口。"""

from .dependencies import DependencyRegistry


def bootstrap(dependencies: dict[str, object] | None = None) -> DependencyRegistry:
    """把应用层提供的依赖放入注册表；不在此处建立网络连接。"""
    registry = DependencyRegistry()
    for name, value in (dependencies or {}).items():
        registry.register(name, value)
    return registry


# TODO: 应用服务确定后，在此接入配置加载、遥测初始化与生命周期关闭钩子。
