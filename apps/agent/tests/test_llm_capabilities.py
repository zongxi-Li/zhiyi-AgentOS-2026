import sys
from types import SimpleNamespace

from app.llm.capabilities import (
    adapt_chat_completion_parameters,
    normalize_model_request,
    normalize_thinking_mode,
    provider_model_capabilities,
)
from app.llm.contracts import (
    LLMInvocationResult,
    LLMUsage,
    ModelInvocationAudit,
    ProviderRawResult,
    ThinkingMode,
)
from app.llm.config import LLMConfig
from app.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.ai_engine.deepseekadapter import DeepSeekAdapter


def test_legacy_thinking_values_map_to_three_internal_modes():
    assert normalize_thinking_mode("off") == ThinkingMode.DISABLED
    assert normalize_thinking_mode("low") == ThinkingMode.STANDARD
    assert normalize_thinking_mode("medium") == ThinkingMode.STANDARD
    assert normalize_thinking_mode("high") == ThinkingMode.DEEP
    assert normalize_thinking_mode("max") == ThinkingMode.DEEP


def test_deepseek_legacy_models_migrate_with_compatible_defaults():
    chat = normalize_model_request("deepseek-chat")
    assert chat.effective_model == "deepseek-flash"
    assert chat.effective_thinking_mode == ThinkingMode.DISABLED

    reasoner = normalize_model_request("deepseek-reasoner")
    assert reasoner.effective_model == "deepseek-flash"
    assert reasoner.effective_thinking_mode == ThinkingMode.STANDARD

    retired = normalize_model_request("deepseek-v4-flash")
    assert retired.effective_model == "deepseek-flash"


def test_official_new_model_name_automatically_gets_family_capabilities():
    """官方新名无需改代码即获得供应商族能力（映射不依赖具体型号）。"""
    current = provider_model_capabilities("deepseek-flash", "https://api.deepseek.com/v1")
    assert current.supports_thinking is True
    assert current.supports_reasoning_effort is True
    assert current.reasoning_efforts == ["low", "high", "max"]
    assert current.default_reasoning_effort == "high"
    assert current.reasoning_effort_aliases["xhigh"] == "high"
    assert current.version == "DeepSeek-V4.1-Flash"

    future = provider_model_capabilities("deepseek-v9-turbo", "https://api.deepseek.com/v1")
    assert future.supports_thinking is True
    assert future.supports_reasoning_effort is True
    assert future.version is None  # 未收录的元数据回落空，不编造

    assert provider_model_capabilities(
        "glm-5.3-flash", "https://open.bigmodel.cn/api/paas/v4"
    ).reasoning_efforts == ["low", "high", "max"]


def test_deepseek_capabilities_include_tool_call_protocol_requirements():
    capabilities = provider_model_capabilities(
        "deepseek-v4-pro", "https://api.deepseek.com/v1"
    )
    assert capabilities.supports_thinking is True
    assert capabilities.supports_reasoning_effort is True
    assert capabilities.supports_tool_choice_in_thinking is False
    assert capabilities.requires_reasoning_content_for_tool_calls is True
    assert capabilities.requires_non_null_assistant_content_for_tool_calls is True
    assert capabilities.supports_json_object is True
    assert capabilities.supports_json_schema is False
    assert capabilities.version == "DeepSeek-V4-Pro-0813"
    assert capabilities.context_window_tokens == 1_000_000
    assert capabilities.max_output_tokens == 384_000


def test_glm_capabilities_use_openai_compatible_thinking_protocol():
    capabilities = provider_model_capabilities(
        "glm-5.2", "https://open.bigmodel.cn/api/paas/v4"
    )
    assert capabilities.supports_thinking is True
    assert capabilities.supports_tools is True
    assert capabilities.supports_json_object is True
    assert capabilities.supports_reasoning_effort is False

    adapted = adapt_chat_completion_parameters(
        model="glm-5.2",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        thinking_mode=ThinkingMode.DEEP,
        parameters={"temperature": 0.2},
    )
    assert adapted.effective_reasoning_effort is None
    assert adapted.parameters == {
        "temperature": 0.2,
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def test_glm_5_3_flash_always_thinks_and_maps_disabled_to_low_effort():
    capabilities = provider_model_capabilities(
        "glm-5.3-flash", "https://open.bigmodel.cn/api/paas/v4"
    )
    assert capabilities.always_thinking is True
    assert capabilities.supports_reasoning_effort is True
    assert ThinkingMode.DISABLED not in capabilities.supported_thinking_modes

    adapted = adapt_chat_completion_parameters(
        model="glm-5.3-flash",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        thinking_mode=ThinkingMode.DISABLED,
    )
    assert adapted.effective_thinking_mode == ThinkingMode.STANDARD
    assert adapted.effective_reasoning_effort == "low"
    assert adapted.parameters == {
        "reasoning_effort": "low",
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def test_glm_5_3_flash_publishes_official_context_window():
    capabilities = provider_model_capabilities(
        "glm-5.3-flash", "https://open.bigmodel.cn/api/coding/paas/v4"
    )
    assert capabilities.context_window_tokens == 1_048_576

    unknown = provider_model_capabilities(
        "glm-unknown-model", "https://open.bigmodel.cn/api/paas/v4"
    )
    assert unknown.context_window_tokens is None


def test_glm_5_3_flash_preserves_each_official_reasoning_effort():
    for effort in ("low", "high", "max"):
        adapted = adapt_chat_completion_parameters(
            model="glm-5.3-flash",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            thinking_mode=ThinkingMode.STANDARD,
            parameters={"reasoning_effort": effort},
        )
        assert adapted.effective_reasoning_effort == effort
        assert adapted.parameters == {
            "reasoning_effort": effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }


def test_glm_5_3_flash_rejects_non_official_reasoning_effort():
    try:
        adapt_chat_completion_parameters(
            model="glm-5.3-flash",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            thinking_mode=ThinkingMode.STANDARD,
            parameters={"reasoning_effort": "medium"},
        )
    except ValueError as exc:
        assert "low, high, max" in str(exc)
    else:
        raise AssertionError("GLM-5.3-Flash accepted an unsupported reasoning effort")


def test_custom_compatible_endpoint_does_not_inherit_official_model_limits():
    capabilities = provider_model_capabilities(
        "deepseek-v4-flash", "https://llm.internal.example/v1"
    )
    assert capabilities.context_window_tokens is None
    assert capabilities.max_output_tokens is None


def test_deepseek_thinking_request_removes_unsupported_parameters():
    adapted = adapt_chat_completion_parameters(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/v1",
        thinking_mode=ThinkingMode.DEEP,
        parameters={
            "temperature": 0.2,
            "top_p": 0.8,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1,
            "tool_choice": "auto",
        },
    )
    assert adapted.effective_reasoning_effort == "max"
    assert adapted.parameters == {
        "reasoning_effort": "max",
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def test_deepseek_preserves_official_reasoning_efforts_and_aliases():
    expected = {
        "minimal": "low",
        "low": "low",
        "medium": "high",
        "high": "high",
        "xhigh": "high",
        "max": "max",
        "ultra": "max",
    }
    for requested, effective in expected.items():
        adapted = adapt_chat_completion_parameters(
            model="deepseek-flash",
            base_url="https://api.deepseek.com/v1",
            thinking_mode=ThinkingMode.STANDARD,
            parameters={"reasoning_effort": requested},
        )
        assert adapted.effective_reasoning_effort == effective
        assert adapted.parameters["reasoning_effort"] == effective


def test_deepseek_implicit_official_effort_is_not_upgraded_to_max():
    adapted = adapt_chat_completion_parameters(
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
        thinking_mode="high",
    )
    assert adapted.effective_reasoning_effort == "high"
    assert adapted.parameters["reasoning_effort"] == "high"


def test_acg_safe_invocation_result_has_no_reasoning_field():
    fields = LLMInvocationResult.model_fields
    assert "reasoning_content" not in fields
    result = LLMInvocationResult(
        content="final",
        usage=LLMUsage(total_tokens=10),
        audit=ModelInvocationAudit(
            provider="deepseek",
            requested_model="deepseek-v4-pro",
            effective_model="deepseek-v4-pro",
            requested_thinking_mode=ThinkingMode.DEEP,
            effective_thinking_mode=ThinkingMode.DEEP,
            effective_reasoning_effort="max",
        ),
    )
    assert "reasoning_content" not in result.model_dump()


def test_provider_raw_result_keeps_reasoning_provider_private():
    completion = SimpleNamespace(
        id="response-1",
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content="final answer",
                    reasoning_content="private reasoning",
                    tool_calls=None,
                ),
            )
        ],
    )
    raw = OpenAICompatibleProvider._extract_raw_result(completion)
    assert isinstance(raw, ProviderRawResult)
    assert raw.reasoning_content == "private reasoning"
    assert raw.content == "final answer"


def test_json_provider_prompt_contains_the_supplied_schema():
    prompt = OpenAICompatibleProvider._json_system_prompt({
        "type": "object",
        "required": ["parties"],
        "properties": {"parties": {"type": "array"}},
    })
    assert '"required":["parties"]' in prompt
    assert '"parties":{"type":"array"}' in prompt


def test_openai_compatible_provider_uses_one_explicit_request_budget(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=fake_openai))
    OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="deepseek-v4-flash",
        timeout_seconds=120,
    )

    assert captured["timeout"] == 120
    assert captured["max_retries"] == 0


def test_llm_config_default_budget_supports_deep_report_generation(monkeypatch):
    monkeypatch.delenv("AGENTOS_LLM_TIMEOUT_SECONDS", raising=False)
    assert LLMConfig.from_env().timeout_seconds == 120


def test_llm_config_can_select_glm_without_removing_deepseek_fallback(monkeypatch):
    for name in (
        "AGENTOS_LLM_BASE_URL",
        "AGENTOS_LLM_API_KEY",
        "AGENTOS_LLM_API_KEY_FILE",
        "AGENTOS_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTOS_LLM_PROVIDER", "glm")
    monkeypatch.setenv("GLM_API_KEY", "glm-secret")
    monkeypatch.setenv("GLM_MODEL", "glm-test")
    monkeypatch.setenv("GLM_BASE_URL", "https://glm.example/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")

    config = LLMConfig.from_env()

    assert (config.provider, config.model, config.base_url, config.api_key) == (
        "glm",
        "glm-test",
        "https://glm.example/v1",
        "glm-secret",
    )


def test_openai_provider_maps_commit_id_to_idempotency_header():
    provider = object.__new__(OpenAICompatibleProvider)
    provider.model = "deepseek-v4-flash"
    provider.base_url = "https://api.example.test/v1"
    provider.default_thinking_mode = ThinkingMode.DISABLED

    parameters = provider._adapt_parameters({"commit_id": "commit:run:step:0"})

    assert parameters["extra_headers"]["Idempotency-Key"] == "commit:run:step:0"
    assert "commit_id" not in parameters


def test_legacy_deepseek_adapter_uses_v4_and_preserves_non_thinking_default():
    adapter = DeepSeekAdapter(api_key="test-key", model_name="deepseek-chat")
    assert adapter.get_model_name() == "deepseek-flash"
    parameters = adapter._adapt_parameters(
        temperature=0.7,
        max_tokens=512,
        stream=False,
        thinking_mode=None,
        kwargs={},
    )
    assert parameters["temperature"] == 0.7
    assert parameters["extra_body"] == {"thinking": {"type": "disabled"}}
