"""定义受控运行时图内核抛出的结构化错误类型。"""


class RuntimeGraphError(ValueError):
    """Base error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class PatchValidationError(RuntimeGraphError):
    """A patch violates graph, contract, capability, state, or budget rules."""


class PatchConflictError(RuntimeGraphError):
    """A patch conflicts with persisted graph version or replay history."""


__all__ = ["PatchConflictError", "PatchValidationError", "RuntimeGraphError"]
