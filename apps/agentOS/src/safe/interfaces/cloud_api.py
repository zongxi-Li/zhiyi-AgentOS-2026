"""专用激活 HTTPS API；认证器和用例由 bootstrap 显式注入。

不提供聊天、模型下载或客户端代码执行入口；TLS 不消除后段分析激活的风险。
TODO(P6)：增加按主体限流、部署级请求 deadline 和共享配额；当前为单进程研究服务。
"""

import asyncio
from collections.abc import Callable
import math
import re
import threading

from pydantic import ValidationError

from safe.application.continuation import ContinuationService
from safe.application.session import SessionService
from safe.contracts.base import parse_json_object
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.identity import AuthenticatedIdentity
from safe.contracts.inference import Capabilities
from safe.contracts.session import CreateSessionRequest, SessionStatus, StepRequest
from safe.interfaces.http_errors import HTTP_STATUS


def create_cloud_app(*, continuation: ContinuationService, sessions: SessionService,
                     authenticate: Callable[..., AuthenticatedIdentity], approved_digest: str,
                     readiness: Callable[[], bool] | None = None,
                     max_body_bytes: int = 12 * 1024 * 1024, max_metadata_bytes: int = 16 * 1024,
                     body_timeout: float = 10.0, max_inflight: int = 8):
    """显式装配时才导入 FastAPI；只信任 ASGI TLS scheme，不信任转发头。"""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    from starlette.exceptions import HTTPException

    for value, limit in ((max_body_bytes, 12 * 1024 * 1024), (max_metadata_bytes, 16 * 1024), (max_inflight, 128)):
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError("HTTP 容量参数超出已批准上限")
    if type(body_timeout) not in (int, float) or not math.isfinite(body_timeout) or not 0 < body_timeout <= 60:
        raise ValueError("HTTP 正文读取超时无效")
    if not isinstance(approved_digest, str) or re.fullmatch(r"[0-9a-f]{64}", approved_digest) is None:
        raise ValueError("HTTP 制品身份无效")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    slots = threading.BoundedSemaphore(max_inflight)
    admission = threading.Condition()
    admission_open = True
    active_requests = 0

    def close_admission():
        """与请求计数在同一锁内关闭准入，避免就绪检查到线程派发之间的竞态。"""
        nonlocal admission_open
        with admission:
            admission_open = False

    def open_admission():
        nonlocal admission_open
        with admission:
            if active_requests:
                raise RuntimeError("已有请求尚未排空")
            admission_open = True

    async def drain():
        """停止准入并等待正文读取及同步派发全部结束；不强制取消执行器。"""
        close_admission()
        def wait_idle():
            with admission:
                admission.wait_for(lambda: active_requests == 0)
        # 独立于 AnyIO 派发线程池，避免维护线程占用最后一个模型执行槽。
        await asyncio.to_thread(wait_idle)

    app.state.safe_close_admission = close_admission
    app.state.safe_open_admission = open_admission
    app.state.safe_drain = drain
    identifier = r"([A-Za-z0-9_-]{1,128})"
    step_route = re.compile(rf"/safe/v1/sessions/{identifier}/steps")
    query_route = re.compile(rf"/safe/v1/sessions/{identifier}/requests/{identifier}")
    session_route = re.compile(rf"/safe/v1/sessions/{identifier}")

    def error(code):
        return JSONResponse({"code": code.value}, status_code=HTTP_STATUS[code],
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(HTTPException)
    async def unknown_route(request, exc):
        return error(ErrorCode.REQUEST_INVALID)

    async def read_body(request):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_body_bytes:
                raise SafeError(ErrorCode.PAYLOAD_TOO_LARGE)
            body.extend(chunk)
        return bytes(body)

    def dispatch(method, path, body, owner):
        if method == "GET" and path == "/safe/v1/capabilities" and not body:
            return Capabilities(available=True)
        if method == "POST" and path == "/safe/v1/sessions":
            parse_json_object(body)
            value = CreateSessionRequest.model_validate_json(body)
            if value.manifest_digest != approved_digest:
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            return continuation.create(owner)
        match = step_route.fullmatch(path)
        if method == "POST" and match:
            parsed = parse_json_object(body)
            data = parsed.get("activation", {}).get("data") if isinstance(parsed.get("activation"), dict) else None
            # 正文中除 data 原字符之外的字节均计入元数据；转义和额外空白也计入。
            if not isinstance(data, str) or len(body) - len(data.encode("utf-8")) > max_metadata_bytes:
                raise SafeError(ErrorCode.PAYLOAD_TOO_LARGE)
            value = StepRequest.model_validate_json(body)
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value.request_id) is None:
                raise SafeError(ErrorCode.REQUEST_INVALID)
            if value.session_id != match[1]:
                raise SafeError(ErrorCode.SESSION_INVALID)
            return continuation.step(owner, value)
        match = query_route.fullmatch(path)
        if method == "GET" and match and not body:
            return sessions.receipt(owner, match[1], match[2])
        match = session_route.fullmatch(path)
        if method == "DELETE" and match and not body:
            view = sessions.view(owner, match[1])
            return sessions.close(owner, match[1]) if view.status in (SessionStatus.CREATED, SessionStatus.ACTIVE) else view
        raise SafeError(ErrorCode.REQUEST_INVALID)

    async def run_to_completion(function, *args, **kwargs):
        """认证存储和模型同步工作均在线程池执行，取消时等线程交还执行权。"""
        operation = asyncio.create_task(run_in_threadpool(function, *args, **kwargs))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            while not operation.done():
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not operation.cancelled():
                operation.exception()
            raise

    @app.api_route("/safe/v1/{tail:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD"])
    async def handle(request: Request):
        nonlocal active_requests
        acquired = False
        admitted = False
        try:
            with admission:
                if not admission_open or (readiness is not None and not readiness()):
                    raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
                active_requests += 1
                admitted = True
            path = request.url.path
            if (request.scope["scheme"] != "https" or request.scope.get("query_string")
                    or request.scope.get("raw_path", b"") != path.encode("ascii") or len(path) > 512):
                raise SafeError(ErrorCode.AUTHENTICATION_FAILED)
            headers = {}
            for name, value in request.scope["headers"]:
                key = name.decode("ascii").lower()
                if key in headers or len(value) > 1024 or len(headers) >= 32:
                    raise SafeError(ErrorCode.AUTHENTICATION_FAILED)
                headers[key] = value.decode("ascii")
            if headers.get("content-encoding", "identity") != "identity":
                raise SafeError(ErrorCode.REQUEST_INVALID)
            length = headers.get("content-length")
            transfer = headers.get("transfer-encoding")
            if transfer is not None and (length is not None or transfer.lower() != "chunked"):
                raise SafeError(ErrorCode.REQUEST_INVALID)
            if length is not None and (not length.isascii() or not length.isdecimal()):
                raise SafeError(ErrorCode.REQUEST_INVALID)
            if length is not None and int(length) > max_body_bytes:
                raise SafeError(ErrorCode.PAYLOAD_TOO_LARGE)
            # 只接受无参数或单一 UTF-8 声明，避免重复 charset 和未知参数歧义。
            if request.method == "POST" and re.fullmatch(
                    r'application/json(?:\s*;\s*charset\s*=\s*(?:utf-8|"utf-8"))?',
                    headers.get("content-type", "").strip(), flags=re.IGNORECASE) is None:
                raise SafeError(ErrorCode.REQUEST_INVALID)
            acquired = slots.acquire(blocking=False)
            if not acquired:
                raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
            body = await asyncio.wait_for(read_body(request), timeout=body_timeout)
            if length is not None and int(length) != len(body):
                raise SafeError(ErrorCode.REQUEST_INVALID)
            # nonce 可使用有界等待的持久存储；不得阻塞 ASGI 主循环。
            identity = await run_to_completion(authenticate, method=request.method, path=path, headers=headers, body=body)
            if readiness is not None and not readiness():
                raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
            outcome = await run_to_completion(dispatch, request.method, path, body, identity.owner_id)
            return JSONResponse(None if outcome is None else outcome.model_dump(mode="json"),
                                headers={"Cache-Control": "no-store"})
        except SafeError as exc:
            return error(exc.code)
        except (ValidationError, ValueError, UnicodeError, RecursionError):
            return error(ErrorCode.REQUEST_INVALID)
        except Exception:
            return error(ErrorCode.TRANSPORT_UNAVAILABLE)
        finally:
            if acquired:
                slots.release()
            if admitted:
                with admission:
                    active_requests -= 1
                    if active_requests == 0:
                        admission.notify_all()

    return app


__all__ = ["create_cloud_app"]
