"""应用层 HTTP JSON 传输的安全合同测试。"""

from __future__ import annotations

import asyncio
import json

from adapters.http_transport import HttpJsonTransport, RotatingKeyProvider


class _Response:
    """模拟 urllib 的成功响应上下文。"""

    status = 200

    def __enter__(self):
        """返回可读取的响应。"""
        return self

    def __exit__(self, *_args) -> None:
        """不吞没上下文异常。"""
        return None

    def read(self) -> bytes:
        """返回已编码 JSON。"""
        return b'{"choices": []}'


def test_http_transport_sends_auth_and_idempotency_outside_json_payload() -> None:
    """密钥和提交标识必须放在请求头，JSON 正文只保留模型调用数据。"""
    requests = []

    def opener(request, *, timeout: float):
        """记录底层请求，不访问真实网络。"""
        requests.append((request, timeout))
        return _Response()

    transport = HttpJsonTransport(
        base_url="https://model.example/v1/",
        api_key="secret-key",
        request_timeout=12.0,
        opener=opener,
    )

    result = asyncio.run(
        transport.post_json(
            path="/chat/completions",
            payload={"model": "local-chat", "messages": []},
            idempotency_key="commit:run-1:step-1:0",
        )
    )

    request, timeout = requests[0]
    assert request.full_url == "https://model.example/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Idempotency-key") == "commit:run-1:step-1:0"
    assert json.loads(request.data.decode("utf-8")) == {
        "model": "local-chat",
        "messages": [],
    }
    assert timeout == 12.0
    assert result == {"choices": []}


def test_http_transport_reads_rotated_key_for_each_request() -> None:
    """密钥轮换后，新请求必须使用新值，且轮换 API 不返回密钥正文。"""
    requests = []

    def opener(request, *, timeout: float):
        requests.append(request)
        return _Response()

    keys = RotatingKeyProvider("old-key")
    transport = HttpJsonTransport(
        base_url="https://model.example/v1",
        key_provider=keys,
        opener=opener,
    )
    asyncio.run(transport.post_json(path="/chat/completions", payload={}))
    revision = keys.rotate("new-key")
    asyncio.run(transport.post_json(path="/chat/completions", payload={}))

    assert requests[0].get_header("Authorization") == "Bearer old-key"
    assert requests[1].get_header("Authorization") == "Bearer new-key"
    assert revision == 1
