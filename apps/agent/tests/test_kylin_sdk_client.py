import asyncio
import time
from types import SimpleNamespace

from app.ai_engine.kylin_sdk.client import KylinSDKClient


async def test_deepseek_generation_does_not_block_the_event_loop():
    client = KylinSDKClient(api_key="", api_endpoint="http://unused")

    class BlockingDeepSeekAdapter:
        def chat(self, **_kwargs):
            time.sleep(0.15)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(total_tokens=1),
            )

    client.use_deepseek = True
    client.deepseek_adapter = BlockingDeepSeekAdapter()

    started = time.perf_counter()
    generation = asyncio.create_task(client.generate_text("hello"))
    await asyncio.sleep(0.01)
    heartbeat_elapsed = time.perf_counter() - started
    result = await generation
    await client.client.aclose()

    assert heartbeat_elapsed < 0.08
    assert result["text"] == "ok"


async def test_legacy_client_uses_selected_glm_runtime(monkeypatch):
    from app.config import settings
    from app.ai_engine.kylin_sdk.client import KylinAIClient

    monkeypatch.setattr(settings, "TEXT_ENGINE", "glm")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "deepseek-secret")
    monkeypatch.setattr(settings, "GLM_API_KEY", "glm-secret")
    monkeypatch.setattr(settings, "GLM_MODEL", "glm-test")
    monkeypatch.setattr(settings, "GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="glm answer"))],
                usage=SimpleNamespace(
                    prompt_tokens=1,
                    completion_tokens=2,
                    total_tokens=3,
                    reasoning_tokens=None,
                    completion_tokens_details=None,
                ),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            return None

    monkeypatch.setattr("app.ai_engine.model_runtime.AsyncOpenAI", FakeClient)
    client = KylinAIClient(api_key="", api_endpoint="http://unused")
    result = await client.generate_text(prompt="hello")
    assert client._sdk_client_instance is None
    await client.close()

    assert result["text"] == "glm answer"
    assert captured["client"] == {
        "api_key": "glm-secret",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    }
    assert captured["model"] == "glm-test"


async def test_unused_legacy_sdk_is_not_initialized_even_when_closing(monkeypatch):
    from unittest.mock import Mock
    from app.ai_engine.kylin_sdk import client as module

    factory = Mock(side_effect=AssertionError("unused SDK must not be constructed"))
    monkeypatch.setattr(module, "KylinSDKClient", factory)
    client = module.KylinAIClient(api_endpoint="http://unused")
    await client.close()
    factory.assert_not_called()


async def test_legacy_sdk_initializes_once_on_first_multimodal_use(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from app.ai_engine.kylin_sdk import client as module

    sdk = SimpleNamespace(recognize_speech=AsyncMock(return_value={"text": "hello"}), close=AsyncMock())
    factory = Mock(return_value=sdk)
    monkeypatch.setattr(module, "KylinSDKClient", factory)
    client = module.KylinAIClient(api_endpoint="http://unused", timeout=17)
    factory.assert_not_called()
    assert await client.recognize_speech(b"audio") == {"text": "hello"}
    assert await client.recognize_speech(b"again") == {"text": "hello"}
    factory.assert_called_once()
    assert factory.call_args.kwargs["api_endpoint"] == "http://unused"
    assert factory.call_args.kwargs["timeout"] == 17
    sdk.recognize_speech.assert_any_await(b"audio")
    await client.close()
    sdk.close.assert_awaited_once()
