"""Industrial planning pack backed by the shared ACG model runtime."""

from pathlib import Path

from adapters.model.native import NativeGeneralAgent
from service.agents.base import AgentProfile

from .capabilities import INDUSTRIAL_CAPABILITY_IDS, register_industrial_capabilities


ROLE_CAPABILITIES = {
    "industrial_capacity_engineer": ["industrial_capacity_analysis"],
    "industrial_process_engineer": ["industrial_station_design", "industrial_layout_logistics"],
    "industrial_automation_engineer": ["industrial_automation_design"],
    "industrial_architecture_engineer": ["industrial_ot_it_architecture"],
    "industrial_safety_auditor": ["industrial_safety_analysis"],
    "industrial_acceptance_reviewer": ["industrial_acceptance_validation"],
    "industrial_report_integrator": ["industrial_visualization"],
}


class IndustrialModelAgent(NativeGeneralAgent):
    """Role-isolated Agent that reuses the native structured model boundary."""

    def __init__(self, agent_name: str, capabilities: list[str]) -> None:
        super().__init__()
        self.profile = AgentProfile(
            agentName=agent_name,
            domain="industrial",
            capabilities=capabilities,
            capacity=2,
            allowedTools=["knowledge_search", "web_search", "web_extract", "current_datetime", "industrial_calculator"],
            bindingPriority=100,
            description="Industrial specialist using the shared ACG structured model runtime.",
        )


def register_pack(agent_registry, workflow_registry, capability_catalog) -> None:
    register_industrial_capabilities(capability_catalog)
    for name, capabilities in ROLE_CAPABILITIES.items():
        agent_registry.register(IndustrialModelAgent(name, capabilities))
    workflow_registry.load_directory(Path(__file__).resolve().parent / "workflows")


__all__ = ["INDUSTRIAL_CAPABILITY_IDS", "IndustrialModelAgent", "register_pack"]
