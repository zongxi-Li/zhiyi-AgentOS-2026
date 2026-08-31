from __future__ import annotations

import json
import hashlib
import re
from typing import Any, Dict

from app.llm.capabilities import (
    adapt_chat_completion_parameters,
    normalize_model_request,
    provider_model_capabilities,
)
from app.llm.contracts import ProviderRawResult, ProviderToolCall


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "MODEL_PROVIDER_FAILED",
        usage: Dict[str, Any] | None = None,
        finish_reason: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.usage = dict(usage or {})
        self.finish_reason = finish_reason
        self.metadata = dict(metadata or {})


class OpenAICompatibleProvider:
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        provider_name: str | None = None,
    ):
        if not base_url:
            raise LLMProviderError("AGENTOS_LLM_BASE_URL is required for openai-compatible provider")
        if not api_key:
            raise LLMProviderError("AGENTOS_LLM_API_KEY is required for openai-compatible provider")
        if not model:
            raise LLMProviderError("AGENTOS_LLM_MODEL is required for openai-compatible provider")
        from openai import OpenAI

        normalized = normalize_model_request(model)
        self.base_url = base_url
        self.provider_name = provider_name or type(self).provider_name
        self.requested_model = normalized.requested_model
        self.model = normalized.effective_model
        self.default_thinking_mode = normalized.effective_thinking_mode
        self.timeout_seconds = timeout_seconds
        # One explicit request budget is easier to reason about than the SDK default
        # of three hidden attempts. Deep reasoning/report generation commonly needs
        # more than 30 seconds, so retries at that boundary only multiply latency.
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )

    def generate_text(self, prompt: str, **kwargs) -> str:
        try:
            adapted = self._adapt_parameters(kwargs)
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a careful assistant. Return only the requested content."},
                    {"role": "user", "content": prompt},
                ],
                **adapted,
            )
            content = self._extract_raw_result(completion).content
            if not content:
                raise LLMProviderError("OpenAI-compatible provider returned empty content")
            return content
        except Exception as exc:
            raise LLMProviderError(f"OpenAI-compatible text generation failed: {exc}") from exc

    def generate_json(self, prompt: str, schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return dict(self.generate_json_result(prompt, schema, **kwargs)["data"])

    def generate_json_result(self, prompt: str, schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """返回安全 JSON 与真实用量/结束原因，供 AgentOS 审计链消费。

        输出预算合同：调用方未显式指定 ``max_tokens`` 时，默认取能力目录登记的
        ``maxOutputTokens`` 显式随请求发送——"未指定"不得再等价于供应商服务端
        默认额度（那会导致结构化 JSON 被静默截断）。解析出的预算以 ``outputBudget``
        元数据随结果/异常上浮，供审计层盖章 requested/effective/reason。
        """
        capabilities = provider_model_capabilities(self.model, self.base_url)
        budget_field = getattr(capabilities, "max_tokens_field", None) or "max_tokens"
        requested_budget = kwargs.get("max_tokens")
        effective_budget = requested_budget
        if effective_budget is None:
            catalog_max = getattr(capabilities, "max_output_tokens", None)
            if catalog_max:
                kwargs = {**kwargs, "max_tokens": int(catalog_max)}
                effective_budget = int(catalog_max)
        output_budget = {
            "requested": requested_budget,
            "effective": effective_budget,
            "reason": (
                "explicit_request" if requested_budget is not None
                else ("catalog_default" if effective_budget is not None else "provider_default")
            ),
            "field": budget_field,
        }
        try:
            adapted = self._adapt_parameters(kwargs)
            adapted["response_format"] = {"type": "json_object"}
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._json_system_prompt(schema),
                    },
                    {"role": "user", "content": prompt},
                ],
                **adapted,
            )
            raw = self._extract_raw_result(completion)
            finish_reason = str(raw.raw_response_metadata.get("finish_reason") or "") or None
            if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
                raise LLMProviderError(
                    "OpenAI-compatible provider exhausted output capacity",
                    code="MODEL_OUTPUT_EXHAUSTED",
                    usage=raw.raw_usage,
                    finish_reason=finish_reason,
                    metadata={"outputBudget": output_budget},
                )
            content = raw.content
            if not content:
                raise LLMProviderError(
                    "OpenAI-compatible provider returned empty JSON content",
                    code="MODEL_EMPTY_RESPONSE",
                    usage=raw.raw_usage,
                    finish_reason=finish_reason,
                    metadata={"outputBudget": output_budget},
                )
            try:
                data = self._parse_json(content)
            except LLMProviderError as exc:
                # Parsing happens after a successful provider response. Preserve
                # that response's accounting metadata while keeping the semantic
                # error code that drives the existing one-shot JSON repair path.
                raise LLMProviderError(
                    str(exc),
                    code=exc.code,
                    usage=raw.raw_usage,
                    finish_reason=finish_reason,
                    metadata={"outputBudget": output_budget, **exc.metadata},
                ) from exc
            return {
                "data": data,
                "usage": dict(raw.raw_usage),
                "finish_reason": finish_reason,
                "response_id": raw.raw_response_metadata.get("response_id"),
                "outputBudget": output_budget,
            }
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"OpenAI-compatible JSON generation failed: {exc}") from exc

    def _adapt_parameters(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        thinking_mode = kwargs.get("thinking_mode", kwargs.get("reasoning_effort", self.default_thinking_mode))
        commit_id = kwargs.get("commit_id")
        parameters = {
            key: value
            for key, value in kwargs.items()
            if key not in {
                "thinking_mode", "reasoning_effort", "commit_id",
                "prompt_version", "prompt_template_hash",
            } and value is not None
        }
        if kwargs.get("reasoning_effort") is not None:
            parameters["reasoning_effort"] = kwargs["reasoning_effort"]
        parameters.setdefault("temperature", 0.1)
        capabilities = provider_model_capabilities(self.model, self.base_url)
        if "max_tokens" in parameters and capabilities.max_tokens_field != "max_tokens":
            parameters[capabilities.max_tokens_field] = parameters.pop("max_tokens")
        adapted = adapt_chat_completion_parameters(
            model=self.model,
            base_url=self.base_url,
            thinking_mode=thinking_mode,
            parameters=parameters,
        ).parameters
        if isinstance(commit_id, str) and commit_id:
            extra_headers = dict(adapted.get("extra_headers") or {})
            extra_headers.setdefault("Idempotency-Key", commit_id)
            adapted["extra_headers"] = extra_headers
        return adapted

    @staticmethod
    def _json_system_prompt(schema: Dict[str, Any]) -> str:
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        return (
            "Return one valid JSON object matching the supplied JSON Schema exactly. "
            "Do not wrap JSON in markdown fences or include explanatory text. "
            f"JSON Schema: {schema_text}"
        )

    @staticmethod
    def _extract_raw_result(completion: Any) -> ProviderRawResult:
        choice = completion.choices[0] if getattr(completion, "choices", None) else None
        message = getattr(choice, "message", None)
        tool_calls = []
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = getattr(tool_call, "function", None)
            tool_calls.append(
                ProviderToolCall(
                    id=str(getattr(tool_call, "id", "")),
                    type=str(getattr(tool_call, "type", "function")),
                    function={
                        "name": str(getattr(function, "name", "")),
                        "arguments": str(getattr(function, "arguments", "")),
                    },
                )
            )
        usage = getattr(completion, "usage", None)
        raw_usage = usage.model_dump() if hasattr(usage, "model_dump") else {}
        return ProviderRawResult(
            content=str(getattr(message, "content", "") or ""),
            reasoning_content=getattr(message, "reasoning_content", None),
            tool_calls=tool_calls,
            raw_usage=raw_usage,
            raw_response_metadata={
                "finish_reason": getattr(choice, "finish_reason", None),
                "response_id": getattr(completion, "id", None),
            },
        )

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned, flags=re.IGNORECASE)
            if match:
                cleaned = match.group(1)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"Invalid JSON returned by provider: {exc}",
                code="MODEL_OUTPUT_INVALID_JSON",
                metadata={
                    "contentLength": len(cleaned),
                    "contentSha256": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
                    "parseOffset": exc.pos,
                    "parseLine": exc.lineno,
                    "parseColumn": exc.colno,
                    "truncationType": (
                        "possible_eof" if exc.pos >= max(0, len(cleaned) - 16)
                        else "invalid_structure"
                    ),
                },
            ) from exc
        if not isinstance(parsed, dict):
            raise LLMProviderError(
                "Provider JSON response must be an object",
                code="MODEL_OUTPUT_INVALID_JSON",
            )
        return parsed


__all__ = ["LLMProviderError", "OpenAICompatibleProvider"]
