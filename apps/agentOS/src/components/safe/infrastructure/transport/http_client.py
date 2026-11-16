"""有界的 Safe 专用 HTTPS 客户端；不发送原文，不自动重发 step。

TLS 校验证书及主机名，签名覆盖最终请求字节；环境代理和重定向关闭。
TODO(P3)：部署级端到端 deadline 尚需包含服务器执行与查询恢复总时限。
"""

from collections.abc import Callable
from dataclasses import dataclass
import math
import re
import secrets
import ssl
import time
from urllib.parse import urlsplit

from pydantic import ValidationError

from components.safe.contracts.base import parse_json_object
from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.inference import Capabilities
from components.safe.contracts.session import CreateSessionRequest, SessionView, StepReceipt, StepRequest
from components.safe.infrastructure.security.signing import sign_request
from components.safe.ports.credentials import Credential


@dataclass(frozen=True)
class TransportObservation:
    """只记录有效载荷计量与耗时；不保留激活、凭据、URL 或身份。"""
    operation: str
    request_bytes: int
    response_bytes: int
    elapsed_ms: float
    status_code: int


class HttpRemoteTransport:
    """同步传输端口；结果不确定时由本机用例查询回执，客户端不盲重试。"""

    def __init__(self, *, origin: str, credential: Credential, ssl_context: ssl.SSLContext | None = None,
                 timeout: float = 10.0, max_response_bytes: int = 64 * 1024,
                 observer: Callable[[TransportObservation], None] | None = None, http_transport=None):
        import httpx

        if not isinstance(origin, str) or not origin.isascii() or any(c.isspace() for c in origin):
            raise ValueError("HTTPS origin 无效")
        parts = urlsplit(origin)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None
                or parts.path not in ("", "/") or parts.query or parts.fragment or "?" in origin or "#" in origin):
            raise ValueError("只允许显式批准的 HTTPS origin")
        try:
            if parts.port is not None and not 1 <= parts.port <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError("HTTPS origin 端口无效") from None
        if not isinstance(credential, Credential) or credential.revoked or "safe:infer" not in credential.scopes:
            raise ValueError("HTTP 凭据无效")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("HTTP 超时无效")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 1024 * 1024:
            raise ValueError("HTTP 响应限额无效")
        context = ssl_context or ssl.create_default_context()
        if not isinstance(context, ssl.SSLContext) or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise ValueError("不得关闭 TLS 证书或主机名验证")
        self._client = httpx.Client(base_url=origin.rstrip("/"), verify=context, timeout=timeout,
            trust_env=False, follow_redirects=False, transport=http_transport,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))
        self._credential, self._limit, self._observer = credential, max_response_bytes, observer
        self._closed = False

    @staticmethod
    def _id(value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
            raise SafeError(ErrorCode.REQUEST_INVALID)
        return value

    def _request(self, operation, method, path, model, *, body=b"", nullable=False):
        import httpx

        if self._closed:
            raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
        if not isinstance(body, bytes) or len(body) > 12 * 1024 * 1024:
            raise SafeError(ErrorCode.PAYLOAD_TOO_LARGE)
        headers = sign_request(credential=self._credential, method=method, path=path,
                               timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body)
        headers.update({"Accept": "application/json", "Accept-Encoding": "identity"})
        if body:
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        try:
            with self._client.stream(method, path, content=body, headers=headers) as response:
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
                if response.headers.get("content-type", "").split(";", 1)[0].lower().strip() != "application/json":
                    raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
                length = response.headers.get("content-length")
                if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > self._limit):
                    raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    if len(raw) + len(chunk) > self._limit:
                        raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
                    raw.extend(chunk)
                if length is not None and len(raw) != int(length):
                    raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
                if self._observer is not None:
                    # 观察器是可选研究计量出口；其故障不得改变已经提交的业务结果。
                    try:
                        self._observer(TransportObservation(operation, len(body), len(raw),
                            (time.perf_counter() - started) * 1000, response.status_code))
                    except Exception:
                        pass
                raw = bytes(raw)
                if not 200 <= response.status_code < 300:
                    try:
                        value = parse_json_object(raw)
                        code = ErrorCode(value["code"]) if set(value) == {"code"} else ErrorCode.TRANSPORT_UNAVAILABLE
                        if response.status_code == 401:
                            code = ErrorCode.AUTHENTICATION_FAILED
                        elif code is ErrorCode.AUTHENTICATION_FAILED:
                            code = ErrorCode.TRANSPORT_UNAVAILABLE
                    except (ValueError, KeyError):
                        code = ErrorCode.TRANSPORT_UNAVAILABLE
                    raise SafeError(code)
                if nullable and raw == b"null":
                    return None
                parse_json_object(raw)
                return model.model_validate_json(raw)
        except SafeError as exc:
            failure = exc.code
        except (httpx.HTTPError, httpx.StreamError, ValidationError, ValueError, OSError, RecursionError):
            failure = ErrorCode.TRANSPORT_UNAVAILABLE
        # from None 只隐藏打印，仍保留 __context__；在 except 之外新建固定错误。
        raise SafeError(failure)

    def capabilities(self) -> Capabilities:
        return self._request("capabilities", "GET", "/safe/v1/capabilities", Capabilities)

    def create_session(self, manifest_digest: str) -> SessionView:
        body = CreateSessionRequest(manifest_digest=manifest_digest).model_dump_json().encode("utf-8")
        view = self._request("create", "POST", "/safe/v1/sessions", SessionView, body=body)
        if view.manifest_digest != manifest_digest:
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        return view

    def step(self, request: StepRequest) -> StepReceipt:
        checked = StepRequest.model_validate(request.model_dump())
        sid = self._id(checked.session_id)
        self._id(checked.request_id)  # 必须在发送前确保可以用同一 ID 查询恢复回执。
        body = checked.model_dump_json().encode("utf-8")
        receipt = self._request("step", "POST", f"/safe/v1/sessions/{sid}/steps", StepReceipt, body=body)
        if (receipt.session_id, receipt.request_id, receipt.step) != (sid, checked.request_id, checked.step):
            raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID)
        return receipt

    def query(self, session_id: str, request_id: str) -> StepReceipt | None:
        sid, rid = self._id(session_id), self._id(request_id)
        receipt = self._request("query", "GET", f"/safe/v1/sessions/{sid}/requests/{rid}", StepReceipt, nullable=True)
        if receipt is not None and (receipt.session_id, receipt.request_id) != (sid, rid):
            raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID)
        return receipt

    def close_session(self, session_id: str) -> SessionView:
        sid = self._id(session_id)
        view = self._request("close_session", "DELETE", f"/safe/v1/sessions/{sid}", SessionView)
        if view.session_id != sid:
            raise SafeError(ErrorCode.SESSION_INVALID)
        return view

    def close(self) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True


__all__ = ["HttpRemoteTransport", "TransportObservation"]
