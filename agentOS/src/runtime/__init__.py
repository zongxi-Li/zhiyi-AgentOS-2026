"""运行时部件的包边界；业务实现将在后续迁移。"""

__all__: list[str] = []
"""运行时部件的公共入口。

恢复控制器会在运行时初始化之前使用锁模块，因此这里采用惰性导出，避免
``recovery -> runtime.compatibility -> runtime`` 形成包初始化环。
"""

from .bootstrap import bootstrap


def __getattr__(name: str):
    if name in {"ApplicationSetup", "ApplicationSetupError", "ModelSetup"}:
        from .app_setup import ApplicationSetup, ApplicationSetupError, ModelSetup

        return {
            "ApplicationSetup": ApplicationSetup,
            "ApplicationSetupError": ApplicationSetupError,
            "ModelSetup": ModelSetup,
        }[name]
    if name in {"ExecutionRuntime", "build_default_runtime"}:
        from .workflow_runtime import ExecutionRuntime, build_default_runtime

        return {
            "ExecutionRuntime": ExecutionRuntime,
            "build_default_runtime": build_default_runtime,
        }[name]
    raise AttributeError(name)


__all__ = [
    "ApplicationSetup",
    "ApplicationSetupError",
    "ModelSetup",
    "ExecutionRuntime",
    "bootstrap",
    "build_default_runtime",
]
