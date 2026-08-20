"""注册模型到原生 Agent 运行时的桥接合同测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.model_adapter import StructuredGenerationError
from adapters.openai_runtime import ModelInvocationError
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
    ModelInvocationResponse,
)


class _Provider:
    """记录统一模型请求，避免测试依赖网络或供应商 SDK。"""

    def __init__(
        self,
        *,
        capability_id: str = "model.local.chat",
        priority: int = 0,
        failure_code: str | None = None,
        delay_seconds: float = 0.0,
        version: str = "v1",
    ) -> None:
        self.requests: list[ModelInvocationRequest] = []
        self.capability_id = capability_id
        self.priority = priority
        self.failure_code = failure_code
        self.delay_seconds = delay_seconds
        self.version = version

    @property
    def manifest(self) -> CapabilityManifest:
        """声明一个可由注册表精确解析的模型。"""
        return CapabilityManifest(
            capabilityId=self.capability_id,
            kind=CapabilityKind.MODEL,
            displayName="Local chat",
            provider="openai_compatible",
            capabilities=["local-chat"],
            metadata={"priority": self.priority},
            version=self.version,
        )

    def is_available(self) -> bool:
        """测试提供商始终可用。"""
        return True

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResponse:
        """回传统一 JSON 输出，并记录模型桥接后的请求。"""
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.failure_code is not None:
            raise ModelInvocationError(self.failure_code, "provider failed")
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


def test_registered_runtime_uses_backup_after_primary_temporary_failure() -> None:
    """主实现调用时临时失败，必须在同一请求内切换至健康备实现。"""
    primary = _Provider(
        capability_id="model.local.primary",
        priority=100,
        failure_code="MODEL_TEMPORARY_UNAVAILABLE",
    )
    backup = _Provider(capability_id="model.local.backup", priority=10)
    registry = ModelCompatibilityRegistry()
    registry.register(primary)
    registry.register(backup)
    runtime = RegisteredModelRuntime(
        registry=registry,
        provider="openai_compatible",
        model="local-chat",
    )

    result = asyncio.run(
        runtime.generate_json(
            prompt="只返回 JSON",
            schema={"type": "object"},
            commit_id="commit:run-1:step-1:0",
        )
    )

    assert result.data == {"answer": "ok"}
    assert len(primary.requests) == 1
    assert len(backup.requests) == 1
    assert backup.requests[0].commit_id == "commit:run-1:step-1:0"


def test_registered_runtime_keeps_timeout_across_all_failover_candidates() -> None:
    """故障切换不能把调用者的总超时按候选数量累加。"""
    primary = _Provider(
        capability_id="model.local.primary",
        priority=100,
    )
    backup = _Provider(
        capability_id="model.local.backup",
        priority=10,
    )
    registry = ModelCompatibilityRegistry()
    registry.register(primary)
    registry.register(backup)
    clock_values = iter((0.0, 0.0, 0.02))
    observed_timeouts: list[float] = []

    async def controlled_timeout(awaitable, timeout: float):
        observed_timeouts.append(timeout)
        awaitable.close()
        raise asyncio.TimeoutError

    runtime = RegisteredModelRuntime(
        registry=registry,
        provider="openai_compatible",
        model="local-chat",
        clock=lambda: next(clock_values),
        wait_for=controlled_timeout,
    )

    with pytest.raises(StructuredGenerationError) as captured:
        asyncio.run(
            runtime.generate_json(
                prompt="只返回 JSON",
                schema={"type": "object"},
                timeout_seconds=0.04,
            )
        )

    assert captured.value.code == "MODEL_TIMEOUT"
    assert observed_timeouts == pytest.approx([0.02, 0.02])


def test_registered_runtime_uses_profile_version_constraint() -> None:
    """桥接运行时必须把冻结版本约束传递到模型注册表。"""
    legacy = _Provider(capability_id="model.version.legacy", version="1.9.0")
    current = _Provider(capability_id="model.version.current", version="2.2.0")
    registry = ModelCompatibilityRegistry()
    registry.register(legacy)
    registry.register(current)
    runtime = RegisteredModelRuntime(
        registry=registry,
        provider="openai_compatible",
        model="local-chat",
        version="^2.0",
    )

    result = asyncio.run(
        runtime.generate_json(prompt="只返回 JSON", schema={"type": "object"})
    )

    assert result.data == {"answer": "ok"}
    assert legacy.requests == []
    assert len(current.requests) == 1
