"""与应用无关的工具运行时注册和调用协议边界。"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Protocol


class ToolRuntime(Protocol):
    """定义 Pack 使用工具运行时所需的最小能力。

    具体实现负责权限、实际工具调用和审计；协议仅传递可序列化参数。调用方可传入
    ``commit_id`` 作为稳定幂等标识，超时、重试和并发保护由包装器统一提供。
    """

    def scoped(self, allowed_tools: Iterable[str]) -> "ToolRuntime":
        """返回仅允许 ``allowed_tools`` 的受限运行时视图。

        实现可返回自身或新对象，但不得扩大权限；未知工具如何处理由执行方法
        规定。输入迭代器可被消费，线程安全与视图生命周期由实现负责。
        """
        ...

    async def run(self, text: str, **kwargs: Any) -> Any:
        """执行面向文本的工具编排请求并返回实现定义的结果。

        ``kwargs`` 用于运行时特定控制参数；异常、取消与结果类型不在协议层被
        转换。调用可能具有外部副作用，调用者负责选择受限视图。
        """
        ...

    async def execute(self, name: str, arguments: dict[str, Any], **kwargs: Any) -> Any:
        """调用名为 ``name`` 的单一工具并返回实现定义的结果。

        ``arguments`` 应可序列化，额外关键字传递运行时控制信息；权限拒绝、参数
        错误、超时和工具失败必须由实现显式报告，不得伪造成功结果。
        """
        ...


ToolRuntimeFactory = Callable[[], ToolRuntime]
_tool_runtime_factory: ToolRuntimeFactory | None = None


def register_tool_runtime_factory(factory: ToolRuntimeFactory) -> None:
    """注册延迟创建工具运行时的全局应用层工厂。

    新工厂覆盖之前的注册值，函数不创建运行时也不关闭旧实例；全局变量无锁，
    因而应用启动期以外的并发替换须由调用方同步。
    """
    global _tool_runtime_factory
    _tool_runtime_factory = factory


def clear_tool_runtime_factory() -> None:
    """移除全局工具运行时工厂，令后续查询返回 ``None``。

    已由其他调用方创建的运行时不受影响，函数不执行资源释放；并发注册和清除
    的可见顺序不由本模块保证，时间与空间复杂度均为 O(1)。
    """
    global _tool_runtime_factory
    _tool_runtime_factory = None


def configured_tool_runtime() -> ToolRuntime | None:
    """若已注册工厂则创建并返回一个工具运行时，否则返回 ``None``。

    每次调用均执行工厂，不缓存实例；工厂异常直接上抛。调用方应把 ``None``
    解释为应用尚未配置工具能力，而非空的可执行运行时。
    """
    return _tool_runtime_factory() if _tool_runtime_factory is not None else None


__all__ = [
    "ToolRuntime",
    "ToolRuntimeFactory",
    "clear_tool_runtime_factory",
    "configured_tool_runtime",
    "register_tool_runtime_factory",
]
