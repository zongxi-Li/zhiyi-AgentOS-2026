"""稳定错误标识；对外消息只使用固定文案，不串联原始异常或用户载荷。

TODO(P0)：冻结错误码表；由 interfaces.http_errors 单独维护 HTTP 映射。
TODO(P4)：增加可查询 request_id；不得把重试建议解释为可重新推进 KV。
"""

from enum import Enum


class ErrorCode(str, Enum):
    MODEL_PARTITION_UNAVAILABLE = "MODEL_PARTITION_UNAVAILABLE"
    ACTIVATION_INVALID = "ACTIVATION_INVALID"
    MANIFEST_INCOMPATIBLE = "MANIFEST_INCOMPATIBLE"
    STEP_OUT_OF_ORDER = "STEP_OUT_OF_ORDER"
    SESSION_INVALID = "SESSION_INVALID"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    PRIVACY_UNAVAILABLE = "PRIVACY_UNAVAILABLE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    TRANSPORT_UNAVAILABLE = "TRANSPORT_UNAVAILABLE"


class SafeError(Exception):
    """仅携带稳定码；详细诊断经独立的去敏审计通道输出。"""

    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code.value)
