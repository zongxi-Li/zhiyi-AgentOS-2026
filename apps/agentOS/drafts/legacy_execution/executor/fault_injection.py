"""执行器可控故障注入；只影响明确指定的步骤和次数。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FaultType(str, Enum):
    """可注入演练故障的受限类型；``NONE`` 表示不注入。"""
    TIMEOUT = "timeout"
    CRASH = "crash"
    EMPTY_EVIDENCE = "empty_evidence"
    NONE = "none"


class InjectedFault(RuntimeError):
    """带机器可读类型的可恢复演示故障。"""
    def __init__(self, fault_type: FaultType, step_id: str, message: str = "") -> None:
        self.fault_type, self.step_id = fault_type, step_id
        super().__init__(message or f"injected {fault_type.value} fault at {step_id}")


@dataclass
class FaultInjector:
    """按指定步骤和次数注入可恢复演练故障。

    该对象维护本实例的触发计数，不跨进程共享；并发调用方应由上层执行图锁
    串行化。超过 ``max_triggers`` 后不再抛错，避免演练配置无限阻断运行。
    """
    step_id: str | None = None
    fault_type: FaultType = FaultType.NONE
    max_triggers: int = 1
    _triggered: int = field(default=0, init=False)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "FaultInjector":
        """从可选配置构造注入器，并把缺失或未知类型收敛为安全默认值。"""
        if not isinstance(config, dict) or not config.get("step_id"):
            return cls()
        try: fault_type = FaultType(str(config.get("fault_type", "timeout")))
        except ValueError: fault_type = FaultType.TIMEOUT
        return cls(str(config["step_id"]), fault_type, max(0, int(config.get("max_triggers", 1))))

    @property
    def active(self) -> bool:
        """返回当前是否配置了可触发的步骤和非 ``NONE`` 故障类型。"""
        return self.step_id is not None and self.fault_type is not FaultType.NONE

    def should_fire(self, step_id: str) -> bool:
        """判断给定步骤是否仍在允许触发次数内，不改变内部计数。"""
        return self.active and step_id == self.step_id and self._triggered < self.max_triggers

    def fire(self, step_id: str) -> None:
        """若步骤命中注入规则则递增计数并抛出 ``InjectedFault``。"""
        if self.should_fire(step_id):
            self._triggered += 1
            raise InjectedFault(self.fault_type, step_id)

    @property
    def triggered_count(self) -> int:
        """返回已触发次数，供检查点恢复和审计读取。"""
        return self._triggered

    def restore_triggered_count(self, value: int) -> None:
        """从检查点恢复非负触发次数；非法负值会被截断为零。"""
        self._triggered = max(0, int(value))


__all__ = ["FaultInjector", "FaultType", "InjectedFault"]
