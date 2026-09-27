"""
错误处理中间件
"""
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
import logging
from app.observability.context import current_trace_id

logger = logging.getLogger(__name__)


def _is_agentos_v2(request: Request) -> bool:
    return "/agentos/v2" in request.url.path


def _request_id() -> str | None:
    return current_trace_id() or None


def _error_code(status_code: int) -> str:
    return {
        400: "AGENTOS_INVALID_REQUEST",
        401: "AGENTOS_UNAUTHORIZED",
        403: "AGENTOS_FORBIDDEN",
        404: "AGENTOS_NOT_FOUND",
        409: "AGENTOS_CONFLICT",
        422: "AGENTOS_VALIDATION_ERROR",
        503: "AGENTOS_UNAVAILABLE",
    }.get(status_code, "AGENTOS_REQUEST_REJECTED")


async def agentos_http_exception_handler(request: Request, exc: HTTPException):
    """Expose one stable error envelope on the AgentOS northbound API."""

    if not _is_agentos_v2(request):
        return await http_exception_handler(request, exc)
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or _error_code(exc.status_code))
        message = str(detail.get("message") or "AgentOS request was rejected.")
    else:
        code = _error_code(exc.status_code)
        message = str(detail or "AgentOS request was rejected.")
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message[:500], "requestId": _request_id()},
        headers=exc.headers,
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理验证异常"""
    if _is_agentos_v2(request):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "AGENTOS_VALIDATION_ERROR",
                "message": "AgentOS request validation failed.",
                "requestId": _request_id(),
            },
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": "参数验证失败",
            "errors": exc.errors(),
            "traceId": current_trace_id(),
        }
    )

async def general_exception_handler(request: Request, exc: Exception):
    """处理通用异常"""
    logger.error("Unhandled request exception. type=%s", type(exc).__name__, exc_info=True)
    if _is_agentos_v2(request):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "AGENTOS_INTERNAL_ERROR",
                "message": "AgentOS service failed to process the request.",
                "requestId": _request_id(),
            },
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "服务器内部错误",
            "error": "INTERNAL_SERVER_ERROR",
            "traceId": current_trace_id(),
        }
    )

