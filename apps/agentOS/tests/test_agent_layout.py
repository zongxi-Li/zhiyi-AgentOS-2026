"""Agent 服务目录迁移边界测试。"""

from __future__ import annotations

from pathlib import Path


def test_agent_service_is_importable_from_service_layer() -> None:
    """Agent 基础模型和注册表必须从 service 层提供，供 Runtime 与部件统一依赖。"""
    from service.agents import AgentProfile, AgentRegistry, BaseAgent

    assert AgentProfile is not None
    assert AgentRegistry is not None
    assert BaseAgent is not None


def test_production_code_no_longer_imports_support_agents() -> None:
    """生产代码不得继续从旧 support.agents 导入，避免迁移后出现双入口。"""
    sources = Path("src").rglob("*.py")

    assert all("support.agents" not in source.read_text(encoding="utf-8") for source in sources)
