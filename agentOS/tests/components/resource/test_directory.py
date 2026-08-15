"""统一资源目录的登记与 Agent 识别行为测试。"""

from __future__ import annotations

import pytest

from components.resource.directory import ResourceConflictError, ResourceDirectory, ResourceNotFoundError
from contracts.capability import CapabilityKind, CapabilityManifest
from service.agents.base import AgentProfile


def _profile(
    agent_id: str,
    *,
    name: str = "analyst",
    domain: str = "general",
    capabilities: list[str] | None = None,
    priority: int = 0,
) -> AgentProfile:
    """构造带稳定身份的最小 Agent 资源描述。"""
    return AgentProfile(
        agentId=agent_id,
        agentName=name,
        domain=domain,
        capabilities=capabilities or ["analyse"],
        bindingPriority=priority,
    )


def test_directory_selects_healthy_scoped_agent_by_priority() -> None:
    """同能力资源应过滤不健康候选后按优先级稳定选择。"""
    directory = ResourceDirectory()
    directory.register_agent(_profile("low", priority=1))
    directory.register_agent(_profile("high", priority=9))
    directory.set_health("high", healthy=False)

    selected = directory.resolve_agent(
        domain="general",
        capability="analyse",
        allowed_agent_ids=["low", "high"],
    )

    assert selected.agent_id == "low"


def test_directory_returns_stable_alternates_after_scope_health_and_exclusion_filters() -> None:
    directory = ResourceDirectory()
    directory.register_agent(_profile("current", priority=20))
    directory.register_agent(_profile("alternate-b", priority=5))
    directory.register_agent(_profile("alternate-a", priority=5))
    directory.register_agent(_profile("unhealthy", priority=10))
    directory.set_health("unhealthy", healthy=False)

    candidates = directory.resolve_agent_candidates(
        domain="general",
        capability="analyse",
        allowed_agent_ids=["current", "alternate-a", "alternate-b", "unhealthy"],
        excluded_agent_ids=["current"],
    )

    assert [item.agent_id for item in candidates] == ["alternate-a", "alternate-b"]


def test_directory_prefers_exact_name_before_capability_fallback() -> None:
    """指定名称时不得被优先级更高的同能力资源替换。"""
    directory = ResourceDirectory()
    directory.register_agent(_profile("named", name="writer", priority=1))
    directory.register_agent(_profile("higher", name="other", priority=9))

    selected = directory.resolve_agent(domain="general", agent_name="writer", capability="analyse")

    assert selected.agent_id == "named"


def test_directory_rejects_conflicting_agent_or_capability_identity() -> None:
    """同一资源身份描述不一致时必须拒绝，禁止静默覆盖。"""
    directory = ResourceDirectory()
    directory.register_agent(_profile("agent-1"))
    with pytest.raises(ResourceConflictError, match="agent-1"):
        directory.register_agent(_profile("agent-1", name="changed"))

    manifest = CapabilityManifest(
        capabilityId="tool.search", kind=CapabilityKind.TOOL, displayName="Search"
    )
    directory.register_capability(manifest)
    with pytest.raises(ResourceConflictError, match="tool.search"):
        directory.register_capability(manifest.model_copy(update={"version": "v2"}))


def test_directory_rejects_disabled_and_out_of_scope_agents() -> None:
    """禁用或不在冻结 scope 内的 Agent 不能通过能力回退被选中。"""
    directory = ResourceDirectory()
    directory.register_agent(_profile("disabled", priority=9).model_copy(update={"enabled": False}))
    directory.register_agent(_profile("out", priority=8))

    with pytest.raises(ResourceNotFoundError):
        directory.resolve_agent(
            domain="general", capability="analyse", allowed_agent_ids=["disabled"]
        )


def test_directory_resolves_healthy_capability_by_identity_and_kind() -> None:
    """模型、Skill、Tool 都应以统一 CapabilityManifest 登记和识别。"""
    directory = ResourceDirectory()
    model = CapabilityManifest(
        capabilityId="model.local", kind=CapabilityKind.MODEL, displayName="Local model"
    )
    tool = CapabilityManifest(
        capabilityId="tool.search", kind=CapabilityKind.TOOL, displayName="Search"
    )
    directory.register_capability(model)
    directory.register_capability(tool)
    directory.set_health("tool.search", healthy=False)

    assert directory.resolve_capability("model.local", kind=CapabilityKind.MODEL) == model
    with pytest.raises(ResourceNotFoundError):
        directory.resolve_capability("tool.search")
    with pytest.raises(ResourceNotFoundError):
        directory.resolve_capability("model.local", kind=CapabilityKind.TOOL)
