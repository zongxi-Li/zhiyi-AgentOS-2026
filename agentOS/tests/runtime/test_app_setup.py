"""应用层模型装配与本地 OpenAI 兼容端点的端到端测试。"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from adapters.model_runtime import RegisteredModelRuntime
from contracts.capability import ModelInvocationRequest
from runtime.app_setup import ApplicationSetup


class _CompatibleHandler(BaseHTTPRequestHandler):
    """提供非流式限流、流式响应和鉴权记录的最小兼容端点。"""

    authorization_headers: list[str | None] = []

    def do_POST(self) -> None:  # noqa: N802
        """按请求类型输出 OpenAI Chat Completions 兼容载荷。"""
        size = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        self.authorization_headers.append(self.headers.get("Authorization"))
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        if self.headers.get("Authorization") == "Bearer primary-key":
            self.send_response(429)
            self.end_headers()
            return
        body = json.dumps(
            {
                "choices": [{"message": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        """禁止测试服务向控制台输出访问正文或请求路径。"""


def test_application_setup_registers_models_refreshes_health_and_closes() -> None:
    """应用层从显式环境装配模型，并在关闭时终止后台健康刷新任务。"""
    environment = {
        "AGENTOS_MODELS": json.dumps(
            [
                {
                    "capabilityId": "model.setup.local",
                    "provider": "openai_compatible",
                    "models": ["local-chat"],
                    "baseUrl": "http://127.0.0.1:19091/v1",
                    "apiKeyEnv": "LOCAL_KEY",
                    "allowInsecure": True,
                }
            ]
        ),
        "LOCAL_KEY": "test-key",
        "AGENTOS_MODEL_HEALTH_INTERVAL_SECONDS": "0.01",
    }

    async def verify() -> None:
        app = ApplicationSetup.from_environment(environment)
        await app.start()
        registry = app.dependencies.require("model_compatibility_registry")
        assert registry.resolve("openai_compatible", "local-chat") is not None
        assert app.started is True
        await asyncio.sleep(0.02)
        await app.close()
        assert app.started is False

    asyncio.run(verify())


def test_application_setup_runs_real_compatible_stream_failover_and_key_rotation() -> None:
    """本地真实 HTTP 服务验证流式响应、429 切换和下一请求使用轮换密钥。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CompatibleHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    _CompatibleHandler.authorization_headers = []
    environment = {
        "AGENTOS_MODELS": json.dumps(
            [
                {
                    "capabilityId": "model.real.primary",
                    "provider": "openai_compatible",
                    "models": ["local-chat"],
                    "baseUrl": base_url,
                    "apiKeyEnv": "PRIMARY_KEY",
                    "allowInsecure": True,
                    "priority": 100,
                },
                {
                    "capabilityId": "model.real.backup",
                    "provider": "openai_compatible",
                    "models": ["local-chat"],
                    "baseUrl": base_url,
                    "apiKeyEnv": "BACKUP_KEY",
                    "allowInsecure": True,
                    "priority": 10,
                },
            ]
        ),
        "PRIMARY_KEY": "primary-key",
        "BACKUP_KEY": "backup-key",
    }

    async def verify() -> None:
        app = ApplicationSetup.from_environment(environment)
        await app.start()
        registry = app.dependencies.require("model_compatibility_registry")
        runtime = RegisteredModelRuntime(
            registry=registry,
            provider="openai_compatible",
            model="local-chat",
        )
        result = await runtime.generate_json(prompt="test", schema={})
        assert result.data == {"answer": "ok"}
        primary = registry.resolve("openai_compatible", "local-chat")
        events = [
            event
            async for event in primary.astream(
                ModelInvocationRequest(requestId="stream-1", model="local-chat")
            )
        ]
        assert [(event.event_type, event.delta) for event in events] == [
            ("delta", "hello"),
            ("completed", ""),
        ]
        app.rotate_key("model.real.primary", "rotated-key")
        events = [
            event
            async for event in primary.astream(
                ModelInvocationRequest(requestId="stream-2", model="local-chat")
            )
        ]
        assert events[-1].event_type == "completed"
        await app.close()

    try:
        asyncio.run(verify())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert _CompatibleHandler.authorization_headers[:2] == [
        "Bearer primary-key",
        "Bearer backup-key",
    ]
    assert _CompatibleHandler.authorization_headers[-1] == "Bearer rotated-key"
