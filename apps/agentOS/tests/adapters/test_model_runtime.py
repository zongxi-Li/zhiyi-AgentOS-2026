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
    ModelCapabilityEnvelope,
    ModelCapabilitySource,
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
        capability: ModelCapabilityEnvelope | None = None,
    ) -> None:
        self.requests: list[ModelInvocationRequest] = []
        self.capability_id = capability_id
        self.priority = priority
        self.failure_code = failure_code
        self.delay_seconds = delay_seconds
        self.version = version
        self.capability = capability

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

    def describe_model(self, model: str) -> ModelCapabilityEnvelope:
        if self.capability is not None:
            return self.capability
        return ModelCapabilityEnvelope.unknown(
            provider="openai_compatible", model=model, version=self.version
        )

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
    assert result.usage == {"completion_tokens": 2}
    assert result.audit_record()["usage"] == {"completion_tokens": 2}
    assert result.prompt_version == "test.v1"
    assert provider.requests[0].model == "local-chat"
    assert provider.requests[0].response_schema == {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
    }
    assert provider.requests[0].options == {"max_tokens": 256}
    assert provider.requests[0].commit_id == "commit:run-1:step-1:0"


def test_registered_runtime_omits_artificial_output_limit_by_default() -> None:
    provider = _Provider()
    registry = ModelCompatibilityRegistry()
    registry.register(provider)
    runtime = RegisteredModelRuntime(
        registry=registry, provider="openai_compatible", model="local-chat"
    )

    result = asyncio.run(runtime.generate_json(prompt="json", schema={"type": "object"}))

    assert provider.requests[0].options == {}
    assert result.output_policy.value == "api_controlled"
    assert result.requested_output_tokens is None
    assert result.capability is not None
    assert result.capability.context_window_tokens is None


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


def test_failover_re_resolves_provider_required_output_field() -> None:
    primary = _Provider(
        capability_id="model.local.primary",
        priority=100,
        failure_code="MODEL_TEMPORARY_UNAVAILABLE",
    )
    backup = _Provider(
        capability_id="model.local.backup",
        priority=10,
        capability=ModelCapabilityEnvelope(
            provider="openai_compatible",
            model="local-chat",
            source=ModelCapabilitySource.ADAPTER_DECLARED,
            maxOutputTokens=777,
            maxTokensField="max_completion_tokens",
            maxTokensRequired=True,
        ),
    )
    registry = ModelCompatibilityRegistry()
    registry.register(primary)
    registry.register(backup)
    runtime = RegisteredModelRuntime(
        registry=registry, provider="openai_compatible", model="local-chat"
    )

    result = asyncio.run(runtime.generate_json(prompt="json", schema={"type": "object"}))

    assert primary.requests[0].options == {}
    assert backup.requests[0].options == {"max_completion_tokens": 777}
    assert result.output_policy.value == "provider_required"
    assert result.effective_output_tokens == 777


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


def test_catalog_declared_budget_is_sent_when_caller_unspecified() -> None:
    """调用方未指定输出额度时，能力目录登记值必须显式随请求发送。

    历史缺陷：max_output_tokens=None 导致请求里完全没有 max_tokens，
    实际输出额度落入供应商服务端默认值，结构化 JSON 被中途截断。
    """
    from contracts.capability import ModelCapabilityEnvelope

    envelope = ModelCapabilityEnvelope.unknown(
        provider="openai_compatible", model="local-chat", version="v1"
    ).model_copy(update={"max_output_tokens": 384000})
    provider = _Provider(capability=envelope)
    registry = ModelCompatibilityRegistry()
    registry.register(provider)
    runtime = RegisteredModelRuntime(
        registry=registry, provider="openai_compatible", model="local-chat"
    )

    result = asyncio.run(runtime.generate_json(
        prompt="只返回 JSON",
        schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    ))

    assert provider.requests, "model was never invoked"
    options = provider.requests[0].options
    assert options.get("max_tokens") == 384000, (
        f"catalog budget not transmitted: options={options}"
    )
    assert result.effective_output_tokens == 384000
    assert result.effective_reason == "catalog_default"


def test_registered_runtime_forwards_validated_reasoning_effort_option() -> None:
    """调用方显式给出的 reasoning_effort 必须进入统一请求选项。

    历史缺陷：桥接层 ``del reasoning_effort`` 把前端档位静默丢弃，
    Mission 全链路的思考档位成为摆设。非法值仍原样忽略，不注入任意供应商参数。
    """
    provider = _Provider()
    registry = ModelCompatibilityRegistry()
    registry.register(provider)
    runtime = RegisteredModelRuntime(
        registry=registry, provider="openai_compatible", model="local-chat"
    )

    asyncio.run(runtime.generate_json(
        prompt="json", schema={"type": "object"}, reasoning_effort="high",
    ))
    asyncio.run(runtime.generate_json(
        prompt="json", schema={"type": "object"}, reasoning_effort="yolo",
    ))
    asyncio.run(runtime.generate_json(prompt="json", schema={"type": "object"}))

    assert provider.requests[0].options == {"reasoning_effort": "high"}
    assert provider.requests[1].options == {}
    assert provider.requests[2].options == {}
