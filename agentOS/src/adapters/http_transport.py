"""应用层 OpenAI 兼容端点的标准库 JSON HTTP 传输。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class HttpTransportError(RuntimeError):
    """表示不暴露请求或响应正文的 HTTP 传输稳定错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HttpJsonTransport:
    """以显式基地址、密钥和超时调用 JSON API 的应用层传输。

    密钥仅保存在传输对象内，并写入 ``Authorization`` Header；`idempotency_key`
    仅写入 HTTP Header。二者均不进入 ``CapabilityManifest``、模型消息、运行 State、
    checkpoint、Trace 或响应错误文字。核心 Runtime 只依赖 ``JsonTransport`` 协议，
    不会自行构造该对象或读取环境变量。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        request_timeout: float = 120.0,
        allow_insecure: bool = False,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        """保存应用层连接配置；默认拒绝明文 HTTP，便于防止密钥误传。"""
        normalized_url = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("HTTP_BASE_URL_INVALID: base_url must be an absolute URL")
        if parsed.scheme != "https" and not allow_insecure:
            raise ValueError("HTTP_BASE_URL_INSECURE: HTTPS is required unless allow_insecure is true")
        if parsed.scheme not in {"https", "http"}:
            raise ValueError("HTTP_BASE_URL_INVALID: only HTTP(S) URLs are supported")
        if request_timeout <= 0:
            raise ValueError("HTTP_TIMEOUT_INVALID: request_timeout must be greater than zero")
        self._base_url = normalized_url
        self._api_key = api_key.strip() if api_key else None
        self._request_timeout = request_timeout
        self._opener = opener

    async def post_json(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """异步提交 JSON；底层标准库阻塞请求在工作线程执行。"""
        return await asyncio.to_thread(
            self._post_json_sync,
            path=path,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def _post_json_sync(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """构造受限请求并映射网络、状态码和 JSON 解析错误。"""
        url = self._url_for(path)
        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HttpTransportError(
                "HTTP_PAYLOAD_INVALID",
                "HTTP payload is not JSON serializable",
            ) from exc
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if idempotency_key and idempotency_key.strip():
            headers["Idempotency-Key"] = idempotency_key.strip()
        request = Request(url=url, data=body, headers=headers, method="POST")
        try:
            with self._opener(request, timeout=self._request_timeout) as response:
                status_value = getattr(response, "status", None)
                status = int(
                    status_value if status_value is not None else response.getcode()
                )
                raw_response = response.read()
        except HTTPError as exc:
            raise HttpTransportError(
                self._code_for_status(exc.code),
                "HTTP provider returned an error response",
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise HttpTransportError(
                "MODEL_TEMPORARY_UNAVAILABLE",
                "HTTP provider connection failed",
            ) from exc
        if status < 200 or status >= 300:
            raise HttpTransportError(
                self._code_for_status(status),
                "HTTP provider returned an error response",
            )
        try:
            parsed = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpTransportError(
                "MODEL_RESPONSE_INVALID",
                "HTTP provider response is not valid JSON",
            ) from exc
        if not isinstance(parsed, dict):
            raise HttpTransportError(
                "MODEL_RESPONSE_INVALID",
                "HTTP provider response must be a JSON object",
            )
        return parsed

    def _url_for(self, path: str) -> str:
        """仅允许相对路径，避免适配器被请求参数诱导访问其他主机。"""
        normalized_path = path.strip()
        parsed = urlsplit(normalized_path)
        if not normalized_path or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise HttpTransportError(
                "HTTP_PATH_INVALID",
                "HTTP path must be a relative path without query or fragment",
            )
        return f"{self._base_url}/{normalized_path.lstrip('/')}"

    @staticmethod
    def _code_for_status(status: int) -> str:
        """将常见供应商 HTTP 状态映射为模型保护层可识别的稳定错误码。"""
        if status == 429:
            return "MODEL_RATE_LIMITED"
        if status in {408, 504}:
            return "MODEL_TIMEOUT"
        if status >= 500:
            return "MODEL_TEMPORARY_UNAVAILABLE"
        return "MODEL_PROVIDER_FAILED"


__all__ = ["HttpJsonTransport", "HttpTransportError"]
