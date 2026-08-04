"""迁移期保留既有故障注入实现，避免复制核心模块。"""

from core.execution.fault_injection import FaultInjector, FaultType, InjectedFault

__all__ = ["FaultInjector", "FaultType", "InjectedFault"]
