"""把应用层 Agent 同步到 Agent 注册表（contracts.resource.AgentProfile）。"""

from __future__ import annotations

from contracts.resource import AgentProfile as RegistryAgentProfile
from contracts.resource import AgentSnapshot, AgentState
from service.agents.base import AgentProfile as AppAgentProfile

from .agent_service import AgentService


class AgentDirectory:
    """应用层 Agent 与 Agent 注册表之间的门面。"""

    def __init__(self, agent_service: AgentService | None = None) -> None:
        self.agent_service = agent_service or AgentService()

    def register_agent(self, profile: AppAgentProfile) -> RegistryAgentProfile:
        """把应用层 Agent 转成注册表 AgentProfile 并登记（幂等）。"""
        agent_id = str(profile.agent_id or profile.agent_name).strip()
        agent_name = str(profile.agent_name).strip()
        domain = str(profile.domain).strip().lower()
        if not agent_id or not agent_name or not domain:
            raise ValueError("agentId, agentName and domain are required")
        declared = {item.strip().lower() for item in profile.capabilities if item.strip()}
        capabilities = tuple(sorted(declared | {f"agent:{agent_name.lower()}"}))
        model_ids = [str(profile.model_name)] if profile.model_name else []
        unified = RegistryAgentProfile(
            agentId=agent_id,
            capabilities=list(capabilities),
            requiredModelIds=model_ids,
            enabled=bool(profile.enabled),
            metadata={
                "directoryKind": "agent",
                "agent": {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "domain": domain,
                    "capabilities": list(capabilities),
                    "version": str(profile.plugin_version or "v1"),
                    "priority": int(profile.binding_priority),
                    "enabled": bool(profile.enabled),
                },
            },
        )
        return self._register_profile(unified)

    def _register_profile(self, profile: RegistryAgentProfile) -> RegistryAgentProfile:
        try:
            existing = self.agent_service.profile(profile.agent_id)
        except KeyError:
            self.agent_service.register(
                profile,
                AgentSnapshot(agentId=profile.agent_id, state=AgentState.IDLE),
            )
            return self.agent_service.profile(profile.agent_id)
        if existing != profile:
            raise ValueError(f"agent conflicts with existing identity: {profile.agent_id}")
        return existing

    def all(self) -> list[RegistryAgentProfile]:
        return self.agent_service.profiles()

    def profile(self, agent_id: str) -> RegistryAgentProfile:
        return self.agent_service.profile(agent_id)
