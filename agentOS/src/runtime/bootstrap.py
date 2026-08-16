"""应用启动的部件装配入口。"""

from adapters.agent_architecture import AgentArchitectureRegistry
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.skill_tool_compatibility import SkillToolCompatibilityRegistry

from .dependencies import DependencyRegistry


def bootstrap(dependencies: dict[str, object] | None = None) -> DependencyRegistry:
    """装配进程级依赖与空能力注册表，不在此处建立网络连接。

    三类兼容注册表始终可用，应用层可在启动后向其中登记适配器。调用方若传入
    同名依赖会显式覆盖默认值，便于测试或自定义生命周期容器接管其所有权。
    """
    registry = DependencyRegistry()
    registry.register("model_compatibility_registry", ModelCompatibilityRegistry())
    registry.register("agent_architecture_registry", AgentArchitectureRegistry())
    registry.register("skill_tool_compatibility_registry", SkillToolCompatibilityRegistry())
    for name, value in (dependencies or {}).items():
        registry.register(name, value)
    return registry


# TODO: 应用服务确定后，在此接入配置加载、遥测初始化与生命周期关闭钩子。
