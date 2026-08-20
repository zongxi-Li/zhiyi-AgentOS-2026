"""应用模型装配复用 Runtime registry 的集成测试。"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from contracts.capability import ModelInvocationRequest
from runtime.app_setup import ApplicationSetup, ApplicationSetupError


class _CompatibleHandler(BaseHTTPRequestHandler):
    authorization_headers: list[str | None] = []

    def do_POST(self) -> None:  # noqa: N802
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
                "choices": [{
                    "message": {"content": '{"answer":"ok"}'},
                    "finish_reason": "stop",
                }],
                "usage": {"completion_tokens": 1},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return None


def _environment(base_url: str) -> dict[str, str]:
    return {
        "AGENTOS_MODELS": json.dumps([
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
        ]),
        "PRIMARY_KEY": "primary-key",
        "BACKUP_KEY": "backup-key",
    }


def test_application_setup_uses_injected_registry_across_lifecycle_restart() -> None:
    """启动、关闭、再启动始终保留同一 registry 与同一适配器。"""
    registry = ModelCompatibilityRegistry()
    app = ApplicationSetup.from_environment({}, model_registry=registry)

    async def verify() -> None:
        assert app.model_registry is registry
        await app.start()
        assert app.started is True
        assert app._health_task is None
        await app.close()
        await app.start()
        assert app.model_registry is registry
        await app.close()

    asyncio.run(verify())


def test_application_setup_runs_real_stream_failover_and_key_rotation() -> None:
    """真实本地 HTTP 验证 registry 路由、429 切换、SSE 与密钥轮换。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CompatibleHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    _CompatibleHandler.authorization_headers = []
    registry = ModelCompatibilityRegistry()

    async def verify() -> None:
        app = ApplicationSetup.from_environment(
            _environment(base_url),
            model_registry=registry,
        )
        await app.start()
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
        assert app.rotate_key("model.real.primary", "rotated-key") == 1
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


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0"])
def test_application_setup_rejects_non_finite_or_non_positive_interval(value: str) -> None:
    with pytest.raises(ApplicationSetupError, match="APP_HEALTH_INTERVAL_INVALID"):
        ApplicationSetup.from_environment(
            {"AGENTOS_MODEL_HEALTH_INTERVAL_SECONDS": value}
        )
