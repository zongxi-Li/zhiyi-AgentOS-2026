"""注册模型到原生 Agent 运行时的桥接合同测试。"""

from __future__ import annotations

import asyncio

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
    ModelInvocationResponse,
)


class _Provider:
    """记录统一模型请求，避免测试依赖网络或供应商 SDK。"""

    def __init__(self) -> None:
        self.requests: list[ModelInvocationRequest] = []

    @property
    def manifest(self) -> CapabilityManifest:
        """声明一个可由注册表精确解析的模型。"""
        return CapabilityManifest(
            capabilityId="model.local.chat",
            kind=CapabilityKind.MODEL,
            displayName="Local chat",
            provider="openai_compatible",
            capabilities=["local-chat"],
        )

    def is_available(self) -> bool:
        """测试提供商始终可用。"""
        return True

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResponse:
        """回传统一 JSON 输出，并记录模型桥接后的请求。"""
        self.requests.append(request)
        return ModelInvocationResponse(
            requestId=request.request_id,
            content={"answer": "ok"},
            provider="openai_compatible",
            model=request.model,
            usage={"completion_tokens": 2},
        )


def test_registered_runtime_converts_native_generation_to_capability_request() -> None:
    """原生 Agent 调用必须保留模型、Schema 和提交标识，并返回结构化结果。"""
    provider = _Provider()
    registry = ModelCompatibilityRegistry()
    registry.register(provider)
    runtime = RegisteredModelRuntime(
        registry=registry,
        provider="openai_compatible",
        model="local-chat",
    )

    result = asyncio.run(
        runtime.generate_json(
            prompt="只返回 JSON",
            schema={"type": "object", "properties": {"answer": {"type": "string"}}},
            max_output_tokens=256,
            prompt_version="test.v1",
            commit_id="commit:run-1:step-1:0",
        )
    )

    assert result.data == {"answer": "ok"}
    assert result.provider == "openai_compatible"
    assert result.model == "local-chat"
    assert result.prompt_version == "test.v1"
    assert provider.requests[0].model == "local-chat"
    assert provider.requests[0].response_schema == {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
    }
    assert provider.requests[0].options == {"max_tokens": 256}
    assert provider.requests[0].commit_id == "commit:run-1:step-1:0"
