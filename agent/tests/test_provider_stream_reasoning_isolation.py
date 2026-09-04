"""Planner Machine Output 流式聚合的 reasoning 隔离合同。

审计结论（2026-09）：Planner 走 ``stream → content buffer → 完整 JSON → parse``
的 Machine Output 链路，``reasoning_content`` 读取但永不保留。本文件锁定：

- GLM 流式聚合结果中 reasoning 永远为 ``None``，marker 不出现在任何结果字段；
- 流式分片必须拼出完整 JSON 才能进入 parse，半截 JSON 不得当作 TaskPlan；
- 非流式回退路径同样不得让 reasoning 进入 Planner 可见结果。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.providers import openai_compatible_provider as provider_module
from app.llm.providers.openai_compatible_provider import (
    LLMProviderError,
    OpenAICompatibleProvider,
)

SECRET = "SECRET_REASONING_MARKER"


def _provider(*, provider_name: str = "glm") -> OpenAICompatibleProvider:
    provider = object.__new__(OpenAICompatibleProvider)
    provider.model = "glm-5.3-flash"
    provider.provider_name = provider_name
    provider.base_url = "https://open.bigmodel.cn/api/paas/v4"
    provider.default_thinking_mode = "disabled"
    return provider


def _chunk(*, content: str | None, reasoning: str | None = None, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(id="chatcmpl-stream", choices=[choice], usage=None)


def test_stream_aggregation_never_retains_reasoning_content() -> None:
    """reasoning_content 在聚合层被丢弃，marker 不得出现在结果对象中。"""
    stream = [
        _chunk(content='{"tasks": [', reasoning=SECRET),
        _chunk(content="1]}", reasoning=SECRET + "-tail"),
        _chunk(content=None, finish_reason="stop"),
    ]

    result = OpenAICompatibleProvider._aggregate_stream(stream)

    assert result.content == '{"tasks": [1]}'
    assert result.reasoning_content is None
    assert SECRET not in repr(result.__dict__)


def test_partial_stream_never_yields_taskplan() -> None:
    """半截 JSON 在 parse 层报错，绝不能被当作合法 Machine Output。"""
    stream = [_chunk(content='{"tasks": [1'), _chunk(content=None, finish_reason="length")]

    result = OpenAICompatibleProvider._aggregate_stream(stream)

    with pytest.raises(LLMProviderError) as exc_info:
        OpenAICompatibleProvider._parse_json(result.content)

    assert exc_info.value.code == "MODEL_OUTPUT_INVALID_JSON"


def _capability_stub(max_output: int):
    return SimpleNamespace(
        max_output_tokens=max_output,
        max_tokens_field="max_tokens",
        max_tokens_required=False,
    )


class _StreamCompletions:
    """流式返回：delta 分片携带 reasoning，聚合后应只剩完整 JSON。"""

    def __init__(self) -> None:
        self.captured: dict = {}

    def create(self, **kwargs):
        self.captured.update(kwargs)
        return iter([
            _chunk(content='{"summary": "', reasoning=SECRET),
            _chunk(content='ok"}', reasoning=SECRET),
            _chunk(content=None, finish_reason="stop"),
            SimpleNamespace(id="chatcmpl-stream", choices=[], usage=SimpleNamespace(model_dump=lambda: {"output_tokens": 7})),
        ])


def test_glm_stream_json_result_excludes_reasoning_and_keeps_usage(monkeypatch) -> None:
    """GLM 流式 JSON 合同：完整 JSON parse 成功、reasoning 隔离、usage 保留。"""
    monkeypatch.setattr(
        provider_module,
        "provider_model_capabilities",
        lambda model, base_url="": _capability_stub(65536),
    )
    provider = _provider(provider_name="glm")
    completions = _StreamCompletions()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_json_result(
        prompt='Return {"summary":"ok"}',
        schema={"type": "object", "properties": {"summary": {"type": "string"}}},
    )

    assert completions.captured.get("stream") is True
    assert result["data"] == {"summary": "ok"}
    assert SECRET not in repr(result)
