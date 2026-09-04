"""每调用超时预算的合同测试：重型调用必须能把超时预算带到供应商请求层。

历史缺陷：provider 的 httpx 客户端是构造期固定的 120 秒读超时，上层
（规划分解器 480s、执行档位 300/600s）无论声明多大的守护预算，连接层
都会先在 120 秒掐线——外层守护从未真正生效（2026-09-01 mission_9af70bb5d340
规划 outline 调用 ReadTimeout 即此根因）。

锁定修复后的合同：
- ``timeout_seconds`` 作为每调用参数透传到 SDK 请求（per-request timeout），
  未指定时不改变客户端默认；
- ``timeout_seconds`` 是传输层预算，绝不能泄漏进 SDK 请求体参数；
- 超时类异常必须升级为 ``code=MODEL_TIMEOUT``（可重试语义），不再伪装成
  通用 provider 故障。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.providers import openai_compatible_provider as provider_module
from app.llm.providers.openai_compatible_provider import LLMProviderError, OpenAICompatibleProvider


def _provider() -> OpenAICompatibleProvider:
    provider = object.__new__(OpenAICompatibleProvider)
    provider.model = "glm-5.3-flash"
    provider.base_url = "https://open.bigmodel.cn/api/paas/v4"
    provider.default_thinking_mode = "disabled"
    return provider


def _capability_stub(max_output: int):
    return SimpleNamespace(
        max_output_tokens=max_output,
        max_tokens_field="max_tokens",
        max_tokens_required=False,
    )


class _FakeCompletion:
    def __init__(self, *, finish_reason: str, content: str = "") -> None:
        choice = SimpleNamespace(
            message=SimpleNamespace(content=content, reasoning_content=None, tool_calls=None),
            finish_reason=finish_reason,
        )
        self.choices = [choice]
        self.id = "chatcmpl-test"
        self.usage = SimpleNamespace(model_dump=lambda: {"output_tokens": 10})


class _CapturingCompletions:
    """记录发往供应商的真实载荷；可改为抛出指定异常。"""

    def __init__(self, *, content: str = '{"summary":"x"}', error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.captured: dict = {}

    def create(self, **kwargs):
        self.captured.update(kwargs)
        if self.error is not None:
            raise self.error
        return _FakeCompletion(finish_reason="stop", content=self.content)


def _patch_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_module,
        "provider_model_capabilities",
        lambda model, base_url="": _capability_stub(65536),
    )


def test_per_call_timeout_reaches_sdk_request(monkeypatch) -> None:
    """调用方声明的超时预算必须原样到达 SDK 请求层。"""
    completions = _CapturingCompletions()
    _patch_capabilities(monkeypatch)
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    provider.generate_json_result(
        prompt='Return {"summary":"x"}',
        schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        timeout_seconds=480,
    )

    assert completions.captured.get("timeout") == 480


def test_timeout_override_never_leaks_into_request_body(monkeypatch) -> None:
    """timeout_seconds 是传输层参数，不得混入聊天补全请求体。"""
    completions = _CapturingCompletions()
    _patch_capabilities(monkeypatch)
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    provider.generate_json_result(
        prompt='Return {"summary":"x"}',
        schema={"type": "object"},
        timeout_seconds=480,
    )

    assert "timeout_seconds" not in completions.captured


def test_default_call_keeps_client_default_timeout(monkeypatch) -> None:
    """未声明超时预算的调用保持客户端默认，不悄悄改语义。"""
    completions = _CapturingCompletions()
    _patch_capabilities(monkeypatch)
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    provider.generate_json_result(prompt="plan", schema={"type": "object"})

    assert "timeout" not in completions.captured


@pytest.mark.parametrize("error_message", [
    "Request timed out.",
    "The read operation timed out",
])
def test_timeout_error_upgrades_to_model_timeout_code(monkeypatch, error_message) -> None:
    """超时异常必须带 MODEL_TIMEOUT 码（可重试语义），不能伪装成通用故障。"""
    completions = _CapturingCompletions(error=RuntimeError(error_message))
    _patch_capabilities(monkeypatch)
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate_json_result(prompt="plan", schema={"type": "object"})

    assert exc_info.value.code == "MODEL_TIMEOUT"


def test_timeout_error_reports_applied_budget(monkeypatch) -> None:
    """超时错误要携带实际生效的超时预算，供审计对账。"""
    completions = _CapturingCompletions(error=RuntimeError("Request timed out."))
    _patch_capabilities(monkeypatch)
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate_json_result(prompt="plan", schema={"type": "object"}, timeout_seconds=480)

    metadata = exc_info.value.metadata
    assert metadata.get("timeoutSeconds") == 480
