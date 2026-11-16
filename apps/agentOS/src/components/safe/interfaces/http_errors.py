"""HTTP 只返回稳定码，不回显输入、凭据、内部异常或 traceback。"""

from components.safe.contracts.errors import ErrorCode

HTTP_STATUS = {
    ErrorCode.MODEL_PARTITION_UNAVAILABLE: 503,
    ErrorCode.MODEL_OUTPUT_INVALID: 503,
    ErrorCode.INFERENCE_INVALID: 400,
    ErrorCode.ACTIVATION_INVALID: 400,
    ErrorCode.MANIFEST_INCOMPATIBLE: 409,
    ErrorCode.STEP_OUT_OF_ORDER: 409,
    ErrorCode.SESSION_INVALID: 404,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.PRIVACY_UNAVAILABLE: 503,
    ErrorCode.BUDGET_EXHAUSTED: 429,
    ErrorCode.AUTHENTICATION_FAILED: 401,
    ErrorCode.TRANSPORT_UNAVAILABLE: 503,
    ErrorCode.REQUEST_INVALID: 400,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
}
