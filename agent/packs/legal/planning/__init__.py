"""Legal Pack planning contributions for the shared AgentOS planning catalog."""

from packs.legal.planning.capabilities import (
    LEGAL_CAPABILITY_AGENT_NAMES,
    LEGAL_CAPABILITY_IDS,
    LEGAL_CAPABILITY_RUNTIME_IDS,
    LEGAL_PLUGIN_ID,
    LEGAL_PLUGIN_VERSION,
    legal_capability_descriptors,
)
from packs.legal.planning.registration import register_legal_capabilities

__all__ = [
    "LEGAL_CAPABILITY_IDS",
    "LEGAL_CAPABILITY_AGENT_NAMES",
    "LEGAL_CAPABILITY_RUNTIME_IDS",
    "LEGAL_PLUGIN_ID",
    "LEGAL_PLUGIN_VERSION",
    "legal_capability_descriptors",
    "register_legal_capabilities",
]
