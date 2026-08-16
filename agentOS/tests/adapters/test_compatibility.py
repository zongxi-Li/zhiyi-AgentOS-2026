"""统一能力注册表的合同测试。"""

from __future__ import annotations

import pytest

from adapters.agent_architecture import AgentArchitectureRegistry
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.skill_tool_compatibility import SkillToolCompatibilityRegistry
from contracts.capability import (
    AgentFramework,
    CapabilityInvocation,
    CapabilityInvocationResult,
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
    ModelInvocationResponse,
    ToolProtocol,
)
from runtime.bootstrap import bootstrap


class _ModelAdapter:
    """提供模型注册表测试所需的最小模型适配器。"""

    def __init__(self, manifest: CapabilityManifest, *, available: bool = True) -> None:
        self._manifest = manifest
        self._available = available

    @property
    def manifest(self) -> CapabilityManifest:
        """返回登记时应被冻结校验的能力声明。"""
        return self._manifest

    def is_available(self) -> bool:
        """模拟可由注册表读取的同步健康状态。"""
        return self._available

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResponse:
        """返回规范化模型结果，具体内容不是本测试重点。"""
        return ModelInvocationResponse(
            requestId=request.request_id,
            content={},
            provider=self.manifest.provider,
            model=request.model,
        )


class _CapabilityAdapter:
    """同时满足 Agent、技能和工具协议的最小适配器。"""

    def __init__(self, manifest: CapabilityManifest, *, available: bool = True) -> None:
        self._manifest = manifest
        self._available = available

    @property
    def manifest(self) -> CapabilityManifest:
        """返回不可变能力声明。"""
        return self._manifest

    def is_available(self) -> bool:
        """模拟不健康的外部实现。"""
        return self._available

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        """提供 Agent 协议所需的方法。"""
        return CapabilityInvocationResult(
            invocationId=invocation.invocation_id,
            success=True,
        )

    async def invoke(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        """提供技能和工具协议所需的方法。"""
        return await self.execute(invocation)


def _manifest(
    *,
    capability_id: str,
    kind: CapabilityKind,
    provider: str = "",
    capabilities: list[str] | None = None,
    metadata: dict | None = None,
) -> CapabilityManifest:
    """生成每个测试都可读的最小能力声明。"""
    return CapabilityManifest(
        capabilityId=capability_id,
        kind=kind,
        displayName=capability_id,
        provider=provider,
        framework=AgentFramework.NATIVE if kind is CapabilityKind.AGENT else None,
        protocol=ToolProtocol.NATIVE if kind in {CapabilityKind.SKILL, CapabilityKind.TOOL} else None,
        capabilities=capabilities or [],
        metadata=metadata or {},
    )


def test_model_registry_resolves_provider_and_model() -> None:
    """模型解析必须以提供商和模型名作为确定性键，并忽略首尾空白。"""
    adapter = _ModelAdapter(
        _manifest(
            capability_id="model.openai.main",
            kind=CapabilityKind.MODEL,
            provider="openai",
            capabilities=["gpt-4o-mini"],
        )
    )
    registry = ModelCompatibilityRegistry()

    registry.register(adapter)

    assert registry.resolve(" OpenAI ", " gpt-4o-mini ") is adapter


def test_model_registry_rejects_conflicting_capability_id() -> None:
    """同一能力 ID 对应不同声明时必须拒绝，不能覆盖既有实现。"""
    registry = ModelCompatibilityRegistry()
    registry.register(
        _ModelAdapter(
            _manifest(
                capability_id="model.shared",
                kind=CapabilityKind.MODEL,
                provider="openai",
                capabilities=["gpt-4o-mini"],
            )
        )
    )

    with pytest.raises(ValueError, match="CAPABILITY_ID_CONFLICT"):
        registry.register(
            _ModelAdapter(
                _manifest(
                    capability_id="model.shared",
                    kind=CapabilityKind.MODEL,
                    provider="deepseek",
                    capabilities=["deepseek-chat"],
                )
            )
        )


def test_model_registry_falls_back_to_lower_priority_healthy_adapter() -> None:
    """同模型高优先级实现不健康时，必须确定性选择次优健康实现。"""
    registry = ModelCompatibilityRegistry()
    primary = _ModelAdapter(
        _manifest(
            capability_id="model.local.primary",
            kind=CapabilityKind.MODEL,
            provider="openai_compatible",
            capabilities=["local-chat"],
            metadata={"priority": 100},
        ),
        available=False,
    )
    backup = _ModelAdapter(
        _manifest(
            capability_id="model.local.backup",
            kind=CapabilityKind.MODEL,
            provider="openai_compatible",
            capabilities=["local-chat"],
            metadata={"priority": 10},
        )
    )

    registry.register(primary)
    registry.register(backup)

    assert registry.resolve("openai_compatible", "local-chat") is backup


def test_agent_registry_rejects_unhealthy_adapter() -> None:
    """不健康的 Agent 适配器不能被解析，以免运行时静默调用失效实现。"""
    adapter = _CapabilityAdapter(
        _manifest(capability_id="agent.native.writer", kind=CapabilityKind.AGENT),
        available=False,
    )
    registry = AgentArchitectureRegistry()
    registry.register(adapter)

    with pytest.raises(LookupError, match="CAPABILITY_UNAVAILABLE"):
        registry.resolve("agent.native.writer")


@pytest.mark.parametrize("kind", [CapabilityKind.SKILL, CapabilityKind.TOOL])
def test_skill_tool_registry_resolves_declared_capability(kind: CapabilityKind) -> None:
    """技能与工具只允许解析自身声明的能力 ID。"""
    adapter = _CapabilityAdapter(
        _manifest(capability_id=f"{kind.value}.native.search", kind=kind)
    )
    registry = SkillToolCompatibilityRegistry()
    registry.register(adapter)

    assert registry.resolve(adapter.manifest.capability_id) is adapter


def test_registry_rejects_wrong_manifest_kind() -> None:
    """模型注册表不得误收 Agent 声明，避免后续错误的调用协议。"""
    registry = ModelCompatibilityRegistry()

    with pytest.raises(ValueError, match="CAPABILITY_KIND_INVALID"):
        registry.register(
            _ModelAdapter(
                _manifest(capability_id="agent.invalid", kind=CapabilityKind.AGENT)
            )
        )


def test_bootstrap_exposes_empty_compatibility_registries() -> None:
    """未配置任何 SDK 时，启动层也应提供可安全填充的三类注册表。"""
    dependencies = bootstrap()

    assert isinstance(
        dependencies.require("model_compatibility_registry"),
        ModelCompatibilityRegistry,
    )
    assert isinstance(
        dependencies.require("agent_architecture_registry"),
        AgentArchitectureRegistry,
    )
    assert isinstance(
        dependencies.require("skill_tool_compatibility_registry"),
        SkillToolCompatibilityRegistry,
    )
