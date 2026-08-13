"""定义受控运行时图内核抛出的结构化错误类型。"""


class RuntimeGraphError(ValueError):
    """携带稳定机器可读错误码的运行图基础异常。"""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class PatchValidationError(RuntimeGraphError):
    """表示补丁违反图、合同、能力、状态或预算规则。"""


class PatchConflictError(RuntimeGraphError):
    """表示补丁与已持久化图版本或重放历史冲突。"""


__all__ = ["PatchConflictError", "PatchValidationError", "RuntimeGraphError"]
