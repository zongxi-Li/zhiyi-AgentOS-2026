"""Lightweight public adapter API; implementations load on first use."""

from importlib import import_module

_EXPORTS = {'FederatedAdapter': ('adapters.model.federated', 'FederatedAdapter'), 'AIService': ('adapters.model.protocols', 'AIService'), 'ModelAdapter': ('adapters.model.protocols', 'ModelAdapter'), 'ModelService': ('adapters.model.protocols', 'ModelService'), 'ModelServiceFactory': ('adapters.model.protocols', 'ModelServiceFactory'), 'StructuredGenerationError': ('adapters.model.protocols', 'StructuredGenerationError'), 'StructuredGenerationResult': ('adapters.model.protocols', 'StructuredGenerationResult'), 'StructuredGenerationRuntime': ('adapters.model.protocols', 'StructuredGenerationRuntime'), 'clear_model_service_factory': ('adapters.model.protocols', 'clear_model_service_factory'), 'register_model_service_factory': ('adapters.model.protocols', 'register_model_service_factory'), 'GuardedModelRuntime': ('adapters.model.guarded', 'GuardedModelRuntime'), 'GuardedToolRuntime': ('adapters.tool.guarded', 'GuardedToolRuntime'), 'ToolInvocationError': ('adapters.tool.guarded', 'ToolInvocationError'), 'AgentArchitectureRegistry': ('adapters.agent.architecture', 'AgentArchitectureRegistry'), 'ModelCompatibilityRegistry': ('adapters.model.compatibility', 'ModelCompatibilityRegistry'), 'JsonTransport': ('adapters.model.openai_runtime', 'JsonTransport'), 'ModelInvocationError': ('adapters.model.openai_runtime', 'ModelInvocationError'), 'OpenAICompatibleRuntime': ('adapters.model.openai_runtime', 'OpenAICompatibleRuntime'), 'RegisteredModelRuntime': ('adapters.model.registered_runtime', 'RegisteredModelRuntime'), 'HttpJsonTransport': ('adapters.transport.http', 'HttpJsonTransport'), 'HttpTransportError': ('adapters.transport.http', 'HttpTransportError'), 'RotatingKeyProvider': ('adapters.transport.http', 'RotatingKeyProvider'), 'LocalRuntimeClient': ('adapters.transport.local_runtime', 'LocalRuntimeClient'), 'LocalRuntimeTransport': ('adapters.transport.local_runtime', 'LocalRuntimeTransport'), 'HttpLocalRuntimeTransport': ('adapters.transport.local_runtime_http', 'HttpLocalRuntimeTransport'), 'LocalRuntimeCredentialProvider': ('adapters.transport.local_runtime_http', 'LocalRuntimeCredentialProvider'), 'LocalRuntimeTransportError': ('adapters.transport.local_runtime_http', 'LocalRuntimeTransportError'), 'SkillToolCompatibilityRegistry': ('adapters.tool.compatibility', 'SkillToolCompatibilityRegistry'), 'ModelProvider': ('adapters.model', 'ModelProvider')}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
