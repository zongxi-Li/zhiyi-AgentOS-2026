from __future__ import annotations

from app.llm.gateway import LLMGateway
from app.llm.providers.openai_compatible_provider import OpenAICompatibleProvider


class _RecordingProvider:
    provider_name = "recording"
    model = "recording-model"

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def generate_text(self, _prompt: str, **kwargs) -> str:
        self.kwargs = kwargs
        return "ok"

    def generate_json(self, _prompt: str, _schema: dict, **kwargs) -> dict:
        self.kwargs = kwargs
        return {"ok": True}


def test_gateway_keeps_prompt_audit_metadata_out_of_provider_request() -> None:
    provider = _RecordingProvider()
    gateway = LLMGateway(provider=provider)

    result = gateway.generate_json(
        "prompt",
        {"type": "object"},
        prompt_version="intent-profile.v2",
        prompt_template_hash="hash-1",
        thinking_mode="disabled",
    )

    assert provider.kwargs == {"thinking_mode": "disabled"}
    assert result["prompt_version"] == "intent-profile.v2"
    assert result["prompt_template_hash"] == "hash-1"


def test_openai_provider_defensively_filters_audit_only_parameters() -> None:
    provider = object.__new__(OpenAICompatibleProvider)
    provider.model = "deepseek-v4-flash"
    provider.base_url = "https://api.deepseek.com/v1"
    provider.default_thinking_mode = "disabled"

    parameters = provider._adapt_parameters({
        "prompt_version": "task-decomposition.v1",
        "prompt_template_hash": "hash-2",
        "max_tokens": 1024,
    })

    assert "prompt_version" not in parameters
    assert "prompt_template_hash" not in parameters
    assert parameters["max_tokens"] == 1024
