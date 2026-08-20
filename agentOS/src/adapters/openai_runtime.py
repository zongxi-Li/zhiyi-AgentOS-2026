"""通过注入 JSON 传输接入 OpenAI Chat Completions 兼容端点。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, AsyncIterator, Protocol

from adapters.http_transport import HttpTransportError
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
    ModelInvocationResponse,
    ModelStreamEvent,
)


class JsonTransport(Protocol):
    """定义由应用层实现的无 SDK JSON 传输边界。

    传输实现负责基地址、认证密钥、HTTP 客户端、连接池与网络重试。适配器只提供
    已规范化的相对路径和 JSON 请求，不保存密钥，也不接触任何供应商 SDK 对象。
    """

    async def post_json(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """提交 JSON 并可将提交标识映射为 HTTP 幂等键，返回已解析对象。"""
        ...

    def stream_json(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式返回已解析 JSON；关闭迭代器时必须释放底层网络响应。"""
        ...


class ModelInvocationError(RuntimeError):
    """表示调用或响应不满足统一模型合同的稳定错误。

    ``code`` 可供应用层映射到审计和重试策略；异常文本不包含提示词、工具参数或
    模型响应正文，避免调用方把敏感内容经 Trace 或日志带出执行边界。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OpenAICompatibleRuntime:
    """把 AgentOS 模型信封映射为 OpenAI 兼容的 Chat Completions 请求。

    此实现同时适用于 OpenAI、DeepSeek、通义兼容模式、Ollama 和 vLLM 等端点，
    前提是应用层注入符合 ``JsonTransport`` 的传输实现。它不发起隐式网络连接，
    不实现 Agent 编排，也不把请求正文写入运行状态、检查点或审计元数据。
    """

    _PATH = "/chat/completions"
    _RESERVED_OPTIONS = frozenset({"model", "messages", "response_format", "stream"})

    def __init__(self, *, manifest: CapabilityManifest, transport: JsonTransport) -> None:
        """保存模型声明和应用层传输，并在启动期验证声明边界。"""
        if manifest.kind is not CapabilityKind.MODEL:
            raise ValueError(
                f"CAPABILITY_KIND_INVALID: expected model, got {manifest.kind.value}"
            )
        if not manifest.provider.strip():
            raise ValueError("MODEL_PROVIDER_INVALID: provider is required")
        if not manifest.capabilities or any(not item.strip() for item in manifest.capabilities):
            raise ValueError(
                "MODEL_CAPABILITIES_INVALID: manifest.capabilities must declare models"
            )
        self._manifest = manifest
        self._transport = transport
        self._models = frozenset(item.strip() for item in manifest.capabilities)

    @property
    def manifest(self) -> CapabilityManifest:
        """返回运行时的不可变模型能力声明，供兼容注册表建立路由。"""
        return self._manifest

    def is_available(self) -> bool:
        """表明运行时已被装配；真实连通性检查由应用层生命周期管理。"""
        return True

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResponse:
        """调用兼容端点并将首个 JSON 响应选择映射回稳定模型信封。"""
        model = request.model.strip()
        if model not in self._models:
            raise ModelInvocationError(
                "MODEL_NOT_SUPPORTED",
                "requested model is not declared by this adapter",
            )
        payload = self._build_payload(request, model)
        try:
            response = await self._transport.post_json(
                path=self._PATH,
                payload=payload,
                idempotency_key=request.commit_id,
            )
        except ModelInvocationError:
            raise
        except HttpTransportError as exc:
            raise ModelInvocationError(exc.code, "OpenAI compatible provider request failed") from exc
        except Exception as exc:
            raise ModelInvocationError(
                "MODEL_PROVIDER_FAILED",
                "OpenAI compatible provider request failed",
            ) from exc
        return self._parse_response(request=request, response=response, model=model)

    async def astream(self, request: ModelInvocationRequest) -> AsyncIterator[ModelStreamEvent]:
        """将 OpenAI 兼容流投影为会话内增量事件，不向运行状态写入正文。"""
        model = request.model.strip()
        if model not in self._models:
            raise ModelInvocationError("MODEL_NOT_SUPPORTED", "requested model is not declared by this adapter")
        streamer = getattr(self._transport, "stream_json", None)
        if not callable(streamer):
            raise ModelInvocationError("MODEL_STREAM_UNSUPPORTED", "transport does not support streaming")
        payload = self._build_payload(request, model)
        payload["stream"] = True
        completed = False
        try:
            async for chunk in streamer(path=self._PATH, payload=payload, idempotency_key=request.commit_id):
                if not isinstance(chunk, Mapping):
                    raise ModelInvocationError("MODEL_RESPONSE_INVALID", "stream chunk is not an object")
                choices = chunk.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
                    continue
                choice = choices[0]
                delta_data = choice.get("delta")
                delta = delta_data.get("content") if isinstance(delta_data, Mapping) else None
                if isinstance(delta, str) and delta:
                    yield ModelStreamEvent(requestId=request.request_id, eventType="delta", delta=delta, provider=self._manifest.provider, model=model)
                if isinstance(delta_data, Mapping):
                    tool_calls = delta_data.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            if not isinstance(tool_call, Mapping):
                                continue
                            function = tool_call.get("function")
                            if not isinstance(function, Mapping):
                                continue
                            arguments = function.get("arguments", "")
                            if not isinstance(arguments, str):
                                continue
                            call_id = tool_call.get("id")
                            name = function.get("name")
                            yield ModelStreamEvent(
                                requestId=request.request_id,
                                eventType="tool_call",
                                provider=self._manifest.provider,
                                model=model,
                                toolCallId=call_id if isinstance(call_id, str) else None,
                                toolName=name if isinstance(name, str) else None,
                                toolArguments=arguments,
                            )
                if isinstance(choice.get("finish_reason"), str):
                    completed = True
                    yield ModelStreamEvent(requestId=request.request_id, eventType="completed", provider=self._manifest.provider, model=model)
                    return
        except HttpTransportError as exc:
            raise ModelInvocationError(exc.code, "OpenAI compatible provider stream failed") from exc
        except ModelInvocationError:
            raise
        except Exception as exc:
            raise ModelInvocationError("MODEL_PROVIDER_FAILED", "OpenAI compatible provider stream failed") from exc
        if not completed:
            raise ModelInvocationError("MODEL_STREAM_INCOMPLETE", "provider stream ended without completion")

    def _build_payload(
        self,
        request: ModelInvocationRequest,
        model: str,
    ) -> dict[str, Any]:
        """构造请求并禁止选项覆盖受合同保护的模型、消息和 JSON Schema。"""
        reserved = self._RESERVED_OPTIONS.intersection(request.options)
        if reserved:
            raise ModelInvocationError(
                "MODEL_OPTIONS_INVALID",
                "options must not override protected OpenAI request fields",
            )
        payload: dict[str, Any] = dict(request.options)
        payload["model"] = model
        payload["messages"] = [dict(message) for message in request.messages]
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agentos_response",
                    "strict": True,
                    "schema": dict(request.response_schema),
                },
            }
        return payload

    def _parse_response(
        self,
        *,
        request: ModelInvocationRequest,
        response: object,
        model: str,
    ) -> ModelInvocationResponse:
        """解析首个 choice 的 JSON 对象，拒绝空、非对象和无效 JSON 响应。"""
        if not isinstance(response, Mapping):
            raise ModelInvocationError("MODEL_RESPONSE_INVALID", "provider response is not an object")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ModelInvocationError("MODEL_RESPONSE_INVALID", "provider response has no usable choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ModelInvocationError("MODEL_RESPONSE_INVALID", "provider response has no message")
        content = self._content_object(message.get("content"))
        usage = response.get("usage")
        finish_reason = choice.get("finish_reason")
        return ModelInvocationResponse(
            requestId=request.request_id,
            content=content,
            provider=self._manifest.provider,
            model=model,
            usage=dict(usage) if isinstance(usage, Mapping) else {},
            metadata={"finishReason": finish_reason} if isinstance(finish_reason, str) else {},
        )

    @staticmethod
    def _content_object(content: object) -> dict[str, Any]:
        """把供应商内容规范为 JSON 对象，不把原始响应嵌入错误信息。"""
        if isinstance(content, Mapping):
            return dict(content)
        if not isinstance(content, str):
            raise ModelInvocationError("MODEL_RESPONSE_INVALID", "provider content is not a JSON object")
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ModelInvocationError(
                "MODEL_RESPONSE_INVALID",
                "provider content is not valid JSON",
            ) from exc
        if not isinstance(parsed, dict):
            raise ModelInvocationError("MODEL_RESPONSE_INVALID", "provider content must be a JSON object")
        return parsed


__all__ = ["JsonTransport", "ModelInvocationError", "OpenAICompatibleRuntime"]
