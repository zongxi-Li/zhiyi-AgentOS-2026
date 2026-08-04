"""执行器可控故障注入；只影响明确指定的步骤和次数。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FaultType(str, Enum):
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
    """配置仅能触发有限次，达到上限后自动恢复正常执行。"""
    step_id: str | None = None
    fault_type: FaultType = FaultType.NONE
    max_triggers: int = 1
    _triggered: int = field(default=0, init=False)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "FaultInjector":
        if not isinstance(config, dict) or not config.get("step_id"):
            return cls()
        try: fault_type = FaultType(str(config.get("fault_type", "timeout")))
        except ValueError: fault_type = FaultType.TIMEOUT
        return cls(str(config["step_id"]), fault_type, max(0, int(config.get("max_triggers", 1))))

    @property
    def active(self) -> bool:
        return self.step_id is not None and self.fault_type is not FaultType.NONE

    def should_fire(self, step_id: str) -> bool:
        return self.active and step_id == self.step_id and self._triggered < self.max_triggers

    def fire(self, step_id: str) -> None:
        if self.should_fire(step_id):
            self._triggered += 1
            raise InjectedFault(self.fault_type, step_id)

    @property
    def triggered_count(self) -> int:
        return self._triggered

    def restore_triggered_count(self, value: int) -> None:
        self._triggered = max(0, int(value))


__all__ = ["FaultInjector", "FaultType", "InjectedFault"]
