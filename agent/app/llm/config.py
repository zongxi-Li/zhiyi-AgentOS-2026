from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "unavailable"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        timeout_raw = (os.getenv("AGENTOS_LLM_TIMEOUT_SECONDS") or "120").strip()
        try:
            timeout_seconds = max(1.0, float(timeout_raw))
        except ValueError:
            timeout_seconds = 120.0

        # 一级配置：显式的 AGENTOS_LLM_* 始终优先。
        provider = (os.getenv("AGENTOS_LLM_PROVIDER") or "").strip().lower()
        base_url = (os.getenv("AGENTOS_LLM_BASE_URL") or "").strip()
        api_key = _read_secret_setting("AGENTOS_LLM_API_KEY")
        model = (os.getenv("AGENTOS_LLM_MODEL") or "").strip()

        provider = _canonical_provider(provider)
        if provider in _NAMED_PROVIDERS:
            defaults = _provider_settings(provider)
            base_url = base_url or defaults["base_url"]
            api_key = api_key or defaults["api_key"]
            model = model or defaults["model"]

        # 二级配置：未显式设置 AGENTOS_LLM_* 时，自动从项目既有的
        # DEEPSEEK_* / GLM_* / DASHSCOPE_* 配置回落映射，让真实模型直接生效，
        # 避免“.env 配了 key 却静默走 mock”的体验陷阱。
        if not provider:
            resolved = _resolve_provider_fallback()
            if resolved:
                provider, base_url, api_key, model = resolved
            else:
                provider = "unavailable"

        return cls(
            provider=provider or "unavailable",
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )


def _resolve_provider_fallback() -> tuple[str, str, str, str] | None:
    """从项目既有的供应商环境变量推断 openai-compatible 配置。

    返回 (provider, base_url, api_key, model)；无可用 key 时返回 None。
    按 TEXT_ENGINE 选择；auto 模式保持 DeepSeek 优先，其次 GLM、通义千问。
    """
    configured_engine = (os.getenv("TEXT_ENGINE") or "auto").strip().lower()
    aliases = {"zhipu": "glm", "dashscope": "qwen"}
    selected_engine = aliases.get(configured_engine, configured_engine)
    if selected_engine not in {"auto", *_NAMED_PROVIDERS}:
        return None
    candidates = (
        (selected_engine,) if selected_engine != "auto"
        else ("deepseek", "glm", "qwen")
    )
    for provider in candidates:
        settings = _provider_settings(provider)
        if settings["enabled"] and _usable_key(settings["api_key"]):
            return provider, settings["base_url"], settings["api_key"], settings["model"]

    return None


_NAMED_PROVIDERS = frozenset({"deepseek", "glm", "qwen"})


def _canonical_provider(provider: str) -> str:
    return {"zhipu": "glm", "dashscope": "qwen"}.get(provider, provider)


def _enabled_setting(name: str) -> bool:
    return (os.getenv(name) or "true").strip().lower() not in {"false", "0", "off", "no"}


def _usable_key(value: str) -> bool:
    return bool(value and not value.startswith("your-"))


def _provider_settings(provider: str) -> dict[str, object]:
    if provider == "deepseek":
        return {
            "api_key": _read_secret_setting("DEEPSEEK_API_KEY"),
            "base_url": (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").strip(),
            "model": (os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash").strip(),
            "enabled": _enabled_setting("DEEPSEEK_ENABLED"),
        }
    if provider == "glm":
        return {
            "api_key": _read_secret_setting("GLM_API_KEY"),
            "base_url": (os.getenv("GLM_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").strip(),
            "model": (os.getenv("GLM_MODEL") or "glm-5.3-flash").strip(),
            "enabled": _enabled_setting("GLM_ENABLED"),
        }
    if provider == "qwen":
        return {
            "api_key": _read_secret_setting("DASHSCOPE_API_KEY") or _read_secret_setting("QWEN_API_KEY"),
            "base_url": (os.getenv("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip(),
            "model": (os.getenv("QWEN_MODEL_BALANCED") or "qwen-plus").strip(),
            "enabled": _enabled_setting("QWEN_ENABLED"),
        }
    raise ValueError(f"unsupported named provider: {provider}")


def _read_secret_setting(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value

    file_path = (os.getenv(f"{name}_FILE") or "").strip()
    if not file_path:
        return ""
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


__all__ = ["LLMConfig"]
