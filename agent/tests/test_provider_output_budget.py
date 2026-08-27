"""输出预算透传的合同测试：能力目录登记值必须显式随请求发送。

历史缺陷：``max_output_tokens=None`` 时请求里完全没有 ``max_tokens``，
384000 只是本地登记，实际输出额度由 DeepSeek 服务端默认策略决定，
结构化 JSON 被中途截断后进入错误的自愈分支（effectiveReason=provider_default）。

锁定修复后的合同：
- 调用方未指定时，默认取能力目录登记的 ``maxOutputTokens`` 显式发送；
- 调用方显式指定的额度永远优先；
- 发生容量耗尽类错误时，LLMProviderError 必须携带 outputBudget 元数据，
  供审计层盖章 requested/effective/reason，杜绝 effectiveOutputTokens=null。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.providers import openai_compatible_provider as provider_module
from app.llm.providers.openai_compatible_provider import LLMProviderError, OpenAICompatibleProvider


def _provider() -> OpenAICompatibleProvider:
    provider = object.__new__(OpenAICompatibleProvider)
    provider.model = "deepseek-v4-flash"
    provider.base_url = "https://api.deepseek.com/v1"
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
    """记录发往供应商的真实载荷，并可指定结束原因与返回内容。"""

    def __init__(self, finish_reason: str = "stop", content: str = "") -> None:
        self.finish_reason = finish_reason
        self.content = content
        self.captured: dict = {}

    def create(self, **kwargs):
        self.captured.update(kwargs)
        return _FakeCompletion(finish_reason=self.finish_reason, content=self.content)


def test_unspecified_budget_resolves_to_catalog_maximum(monkeypatch) -> None:
    """None 不得再等价于"什么都不发"：目录登记值就是随请求发送的值。"""
    completions = _CapturingCompletions(finish_reason="stop", content='{"summary":"x"}')
    monkeypatch.setattr(
        provider_module,
        "provider_model_capabilities",
        lambda model, base_url="": _capability_stub(65536),
    )
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_json_result(
        prompt='Return {"summary":"x"}',
        schema={"type": "object", "properties": {"summary": {"type": "string"}}},
    )

    assert completions.captured.get("max_tokens") == 65536
    budget = dict(result.get("outputBudget") or {})
    assert budget.get("effective") == 65536
    assert budget.get("reason") == "catalog_default"
    assert budget.get("requested") is None


def test_explicit_caller_budget_always_wins(monkeypatch) -> None:
    """调用方显式指定的额度永远优先于目录默认，且审计如实记录。"""
    completions = _CapturingCompletions(finish_reason="stop", content='{"summary":"x"}')
    monkeypatch.setattr(
        provider_module,
        "provider_model_capabilities",
        lambda model, base_url="": _capability_stub(65536),
    )
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_json_result(
        prompt='Return {"summary":"x"}',
        schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        max_tokens=4096,
    )

    assert completions.captured.get("max_tokens") == 4096
    budget = dict(result.get("outputBudget") or {})
    assert budget.get("requested") == 4096
    assert budget.get("effective") == 4096
    assert budget.get("reason") == "explicit_request"


def test_exhaustion_error_carries_output_budget_metadata(monkeypatch) -> None:
    """"截断异常必须携带真实发送/生效额度，供审计层消灭 null。"""
    completions = _CapturingCompletions(finish_reason="length")
    monkeypatch.setattr(
        provider_module,
        "provider_model_capabilities",
        lambda model, base_url="": _capability_stub(65536),
    )
    provider = _provider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate_json_result(
            prompt='Return {"summary":"x"}', schema={"type": "object"}
        )

    assert exc_info.value.code == "MODEL_OUTPUT_EXHAUSTED"
    budget = dict(getattr(exc_info.value, "metadata", {}) or {}).get("outputBudget") or {}
    assert budget.get("effective") == 65536, f"budget metadata missing: {budget}"
    assert budget.get("reason") == "catalog_default"
    # 服务端确实收到了显式 max_tokens，而不是默默用默认额度。
    assert completions.captured.get("max_tokens") == 65536
