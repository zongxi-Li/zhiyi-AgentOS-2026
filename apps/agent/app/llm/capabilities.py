from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.llm.contracts import ProviderModelCapabilities, ThinkingMode


DEEPSEEK_DEFAULT_MODEL = "deepseek-flash"
DEEPSEEK_LEGACY_MODELS = {
    "deepseek-chat": (DEEPSEEK_DEFAULT_MODEL, ThinkingMode.DISABLED),
    "deepseek-reasoner": (DEEPSEEK_DEFAULT_MODEL, ThinkingMode.STANDARD),
    # 官方 2026-09 起推荐 deepseek-flash；旧名仍被服务端接受，此处只做归一
    "deepseek-v4-flash": (DEEPSEEK_DEFAULT_MODEL, ThinkingMode.DISABLED),
}
GLM_5_3_FLASH_REASONING_EFFORTS = ("low", "high", "max")

# ---- 供应商族判定（品牌级，不含模型版本名；官方上新/改名无需改代码） ----

_PROVIDER_ID_ALIASES = {
    "deepseek": "deepseek",
    "glm": "glm",
    "zhipu": "glm",
    "zhipuai": "glm",
    "qwen": "qwen",
    "dashscope": "qwen",
}
_PROVIDER_OFFICIAL_DOMAINS = (
    ("api.deepseek.com", "deepseek"),
    ("bigmodel.cn", "glm"),
    ("dashscope.aliyuncs.com", "qwen"),
)


def provider_family(provider: str = "", base_url: str = "", model: str = "") -> str:
    """判定供应商族：显式供应商标识 > 官方域名 > 模型名品牌提示。

    模型名只作为第三方中转端点的兜底提示，且只匹配品牌（deepseek/glm-/qwen），
    不匹配任何版本号或具体型号——具体模型清单始终以供应商 /models 目录为准。
    """
    family = _PROVIDER_ID_ALIASES.get((provider or "").strip().lower())
    if family:
        return family
    normalized_url = (base_url or "").lower()
    for domain, domain_family in _PROVIDER_OFFICIAL_DOMAINS:
        if domain in normalized_url:
            return domain_family
    normalized_model = (model or "").strip().lower()
    if "deepseek" in normalized_model:
        return "deepseek"
    if "glm-" in normalized_model:
        return "glm"
    if "qwen" in normalized_model:
        return "qwen"
    return ""


# ---- 每模型官方元数据覆盖（可选，查不到回落供应商级默认） ----

# Official context windows (tokens) from docs.bigmodel.cn. Only models with a
# published figure are listed; unknown GLM models stay None so the UI can say
# "上限未声明" instead of inventing a ceiling.
GLM_CONTEXT_WINDOWS = {
    "glm-5.3-flash": 1_048_576,
}

# 不可关思考等供应商目录无法表达的特例。未收录的 GLM 模型回落"可关思考"
# 的通用语义，新模型名自动兼容。
GLM_MODEL_OVERRIDES = {
    "glm-5.3-flash": {
        "always_thinking": True,
        "reasoning_efforts": GLM_5_3_FLASH_REASONING_EFFORTS,
    },
}

# version 展示名 / 上下文窗口 / 输出上限（仅官方域名下采信）。
DEEPSEEK_MODEL_METADATA = {
    "deepseek-flash": ("DeepSeek-V4.1-Flash", 1_000_000, 384_000),
    "deepseek-v4-pro": ("DeepSeek-V4-Pro-0813", 1_000_000, 384_000),
}

_THINKING_MODE_ALIASES = {
    "": ThinkingMode.DISABLED,
    "off": ThinkingMode.DISABLED,
    "none": ThinkingMode.DISABLED,
    "disabled": ThinkingMode.DISABLED,
    "false": ThinkingMode.DISABLED,
    "low": ThinkingMode.STANDARD,
    "medium": ThinkingMode.STANDARD,
    "standard": ThinkingMode.STANDARD,
    "high": ThinkingMode.DEEP,
    "xhigh": ThinkingMode.DEEP,
    "max": ThinkingMode.DEEP,
    "deep": ThinkingMode.DEEP,
}


@dataclass(frozen=True)
class NormalizedModelRequest:
    requested_model: str
    effective_model: str
    requested_thinking_mode: ThinkingMode
    effective_thinking_mode: ThinkingMode
    resolution_reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AdaptedProviderRequest:
    parameters: Dict[str, Any]
    effective_thinking_mode: ThinkingMode
    effective_reasoning_effort: Optional[str]
    resolution_reasons: List[str] = field(default_factory=list)


def normalize_thinking_mode(value: str | ThinkingMode | None) -> ThinkingMode:
    if isinstance(value, ThinkingMode):
        return value
    normalized = str(value or "").strip().lower()
    try:
        return _THINKING_MODE_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported thinking mode: {value}") from exc


def normalize_deepseek_model(model: str) -> str:
    normalized = (model or "").strip()
    legacy = DEEPSEEK_LEGACY_MODELS.get(normalized.lower())
    return legacy[0] if legacy else normalized


def normalize_model_request(
    model: str,
    thinking_mode: str | ThinkingMode | None = None,
) -> NormalizedModelRequest:
    requested_model = (model or "").strip()
    legacy = DEEPSEEK_LEGACY_MODELS.get(requested_model.lower())
    reasons: List[str] = []

    if legacy:
        effective_model, legacy_mode = legacy
        reasons.append(f"legacy_model_migrated:{requested_model}->{effective_model}")
        requested_mode = normalize_thinking_mode(thinking_mode) if thinking_mode is not None else legacy_mode
        if thinking_mode is None:
            reasons.append(f"legacy_thinking_mode_migrated:{legacy_mode.value}")
    else:
        effective_model = requested_model
        requested_mode = normalize_thinking_mode(thinking_mode)

    return NormalizedModelRequest(
        requested_model=requested_model,
        effective_model=effective_model,
        requested_thinking_mode=requested_mode,
        effective_thinking_mode=requested_mode,
        resolution_reasons=reasons,
    )


def provider_model_capabilities(
    model: str,
    base_url: str = "",
    provider: str = "",
) -> ProviderModelCapabilities:
    normalized_model = normalize_deepseek_model(model).lower()
    normalized_url = (base_url or "").lower()
    family = provider_family(provider=provider, base_url=base_url, model=model)

    if family == "glm":
        overrides = GLM_MODEL_OVERRIDES.get(normalized_model, {})
        always_thinking = bool(overrides.get("always_thinking", False))
        return ProviderModelCapabilities(
            supports_thinking=True,
            always_thinking=always_thinking,
            supported_thinking_modes=(
                {ThinkingMode.STANDARD, ThinkingMode.DEEP}
                if always_thinking
                else {
                    ThinkingMode.DISABLED,
                    ThinkingMode.STANDARD,
                    ThinkingMode.DEEP,
                }
            ),
            supports_reasoning_effort=always_thinking,
            reasoning_efforts=(
                list(overrides["reasoning_efforts"]) if always_thinking and overrides.get("reasoning_efforts") else None
            ),
            supports_tools=True,
            supports_json_object=True,
            supports_json_schema=False,
            supports_stream_usage=False,
            max_tokens_field="max_tokens",
            # A conservative explicit ceiling for structured AgentOS calls.
            # Individual operations request smaller budgets and the provider
            # adapter clamps them to this declared maximum.
            max_output_tokens=65_536,
            context_window_tokens=GLM_CONTEXT_WINDOWS.get(normalized_model),
        )

    if family == "deepseek":
        official_metadata = (
            DEEPSEEK_MODEL_METADATA.get(normalized_model)
            if "api.deepseek.com" in normalized_url
            else None
        )
        return ProviderModelCapabilities(
            supports_thinking=True,
            supported_thinking_modes={
                ThinkingMode.DISABLED,
                ThinkingMode.STANDARD,
                ThinkingMode.DEEP,
            },
            supports_reasoning_effort=True,
            reasoning_efforts=["high", "max"],
            supports_tools=True,
            supports_tool_choice_in_thinking=False,
            requires_reasoning_content_for_tool_calls=True,
            requires_non_null_assistant_content_for_tool_calls=True,
            supports_json_object=True,
            supports_json_schema=False,
            supports_developer_role=False,
            supports_stream_usage=True,
            max_tokens_field="max_tokens",
            version=official_metadata[0] if official_metadata else None,
            context_window_tokens=official_metadata[1] if official_metadata else None,
            max_output_tokens=official_metadata[2] if official_metadata else None,
        )

    if family == "qwen" and "qwen3" in normalized_model:
        return ProviderModelCapabilities(
            supports_thinking=True,
            supported_thinking_modes={
                ThinkingMode.DISABLED,
                ThinkingMode.STANDARD,
                ThinkingMode.DEEP,
            },
            supports_reasoning_effort=False,
            supports_tools=True,
            supports_json_object=True,
            supports_stream_usage=True,
            max_tokens_field="max_tokens",
        )

    if normalized_model.startswith(("o1", "o3", "o4", "gpt-5")):
        return ProviderModelCapabilities(
            supports_thinking=True,
            supported_thinking_modes={
                ThinkingMode.DISABLED,
                ThinkingMode.STANDARD,
                ThinkingMode.DEEP,
            },
            supports_reasoning_effort=True,
            supports_tools=True,
            supports_json_object=True,
            supports_json_schema=True,
            supports_developer_role=True,
            supports_stream_usage=True,
            max_tokens_field="max_completion_tokens",
        )

    return ProviderModelCapabilities()


def adapt_chat_completion_parameters(
    *,
    model: str,
    base_url: str,
    thinking_mode: str | ThinkingMode | None,
    parameters: Optional[Dict[str, Any]] = None,
    provider: str = "",
) -> AdaptedProviderRequest:
    mode = normalize_thinking_mode(thinking_mode)
    capabilities = provider_model_capabilities(model, base_url, provider)
    request = dict(parameters or {})
    reasons: List[str] = []

    if capabilities.always_thinking and mode == ThinkingMode.DISABLED:
        reasons.append("thinking_mode_upgraded:disabled->standard")
        mode = ThinkingMode.STANDARD

    if mode not in capabilities.supported_thinking_modes:
        if ThinkingMode.STANDARD in capabilities.supported_thinking_modes and mode == ThinkingMode.DEEP:
            reasons.append("thinking_mode_downgraded:deep->standard")
            mode = ThinkingMode.STANDARD
        elif ThinkingMode.DISABLED in capabilities.supported_thinking_modes:
            reasons.append(f"thinking_mode_downgraded:{mode.value}->disabled")
            mode = ThinkingMode.DISABLED
        else:
            raise ValueError(f"Model {model} does not support thinking mode {mode.value}")

    family = provider_family(provider=provider, base_url=base_url, model=model)
    effective_effort: Optional[str] = None
    if family == "deepseek":
        extra_body = dict(request.get("extra_body") or {})
        if mode == ThinkingMode.DISABLED:
            extra_body["thinking"] = {"type": "disabled"}
            request.pop("reasoning_effort", None)
        else:
            extra_body["thinking"] = {"type": "enabled"}
            effective_effort = "max" if mode == ThinkingMode.DEEP else "high"
            request["reasoning_effort"] = effective_effort
            for key in (
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
            ):
                request.pop(key, None)
            if not capabilities.supports_tool_choice_in_thinking:
                request.pop("tool_choice", None)
        request["extra_body"] = extra_body
    elif family == "glm":
        extra_body = dict(request.get("extra_body") or {})
        if capabilities.always_thinking:
            allowed_efforts = tuple(capabilities.reasoning_efforts or GLM_5_3_FLASH_REASONING_EFFORTS)
            requested_effort = request.get("reasoning_effort")
            if requested_effort is not None:
                requested_effort = str(requested_effort).strip().lower()
                if requested_effort not in allowed_efforts:
                    allowed = ", ".join(allowed_efforts)
                    raise ValueError(
                        f"Model {model} only supports reasoning_effort: {allowed}"
                    )
                effective_effort = requested_effort
            else:
                # Backward-compatible callers still speak in the three internal
                # semantic modes. When no exact provider value was supplied,
                # choose the nearest official GLM strength without disabling
                # thinking on an always-thinking model.
                effective_effort = "max" if mode == ThinkingMode.DEEP else "low"
            request["reasoning_effort"] = effective_effort
            extra_body["thinking"] = {"type": "enabled"}
            mode = ThinkingMode.DEEP if effective_effort in {"high", "max"} else ThinkingMode.STANDARD
        else:
            extra_body["thinking"] = {"type": "enabled" if mode != ThinkingMode.DISABLED else "disabled"}
        request["extra_body"] = extra_body
    elif family == "qwen" and "qwen3" in normalize_deepseek_model(model).lower():
        extra_body = dict(request.get("extra_body") or {})
        if mode == ThinkingMode.DISABLED:
            extra_body["enable_thinking"] = False
        else:
            extra_body["enable_thinking"] = True
            # Thinking mode is a semantic choice. The Harness must not turn it
            # into an invented token ceiling when the provider did not report
            # one; DashScope/API defaults remain authoritative.
            extra_body.pop("thinking_budget", None)
        request["extra_body"] = extra_body
    elif (model or "").strip().lower().startswith(("o1", "o3", "o4", "gpt-5")):
        if mode != ThinkingMode.DISABLED:
            effective_effort = "high" if mode == ThinkingMode.DEEP else "medium"
            request["reasoning_effort"] = effective_effort
        else:
            request.pop("reasoning_effort", None)

    return AdaptedProviderRequest(
        parameters=request,
        effective_thinking_mode=mode,
        effective_reasoning_effort=effective_effort,
        resolution_reasons=reasons,
    )


__all__ = [
    "AdaptedProviderRequest",
    "DEEPSEEK_DEFAULT_MODEL",
    "DEEPSEEK_LEGACY_MODELS",
    "DEEPSEEK_MODEL_METADATA",
    "GLM_5_3_FLASH_REASONING_EFFORTS",
    "GLM_CONTEXT_WINDOWS",
    "GLM_MODEL_OVERRIDES",
    "NormalizedModelRequest",
    "adapt_chat_completion_parameters",
    "normalize_deepseek_model",
    "normalize_model_request",
    "normalize_thinking_mode",
    "provider_family",
    "provider_model_capabilities",
]
