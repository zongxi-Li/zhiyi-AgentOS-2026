"""Provider waiting policy, independent of tool execution and human approval."""
from dataclasses import dataclass
import math
import os


@dataclass(frozen=True)
class ModelStreamPolicy:
    connect: float = 10.0
    first_response: float = 300.0
    idle: float = 300.0
    total: float = 900.0

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in (
            self.connect, self.first_response, self.idle, self.total
        )):
            raise ValueError("MODEL_TIMEOUT_INVALID: model timeouts must be positive and finite")

    @classmethod
    def from_environment(cls):
        return cls(**{name: float(os.getenv(f"MODEL_{key}_TIMEOUT_SECONDS", str(default)))
                      for name, key, default in (
                          ("connect", "CONNECT", 10), ("first_response", "FIRST_RESPONSE", 300),
                          ("idle", "STREAM_IDLE", 300), ("total", "REQUEST_TOTAL", 900))})


class ModelStreamTimeout(TimeoutError):
    def __init__(self, phase: str):
        self.phase = phase
        super().__init__(f"Model {phase} timeout")
