"""Lightweight public adapter API; implementations load on first use."""

from importlib import import_module

_EXPORTS = {'AgentOutput': ('adapters.agent.base', 'AgentOutput'), 'AgentProfile': ('adapters.agent.base', 'AgentProfile'), 'AgentRunContext': ('adapters.agent.base', 'AgentRunContext'), 'BaseAgent': ('adapters.agent.base', 'BaseAgent'), 'AgentNotFound': ('adapters.agent.registry', 'AgentNotFound'), 'AgentRegistry': ('adapters.agent.registry', 'AgentRegistry'), 'AgentDefinition': ('contracts.agents', 'AgentDefinition'), 'AgentRegistrationRef': ('contracts.agents', 'AgentRegistrationRef')}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
