"""AgentOS 的外部系统适配器公共入口。"""

from adapters.federated_adapter import FederatedAdapter
from adapters.model_adapter import (
    AIService,
    ModelAdapter,
    ModelService,
    ModelServiceFactory,
    StructuredGenerationError,
    StructuredGenerationResult,
    StructuredGenerationRuntime,
    clear_model_service_factory,
    register_model_service_factory,
)
from adapters.guarded_model import GuardedModelRuntime
from adapters.guarded_tool import GuardedToolRuntime, ToolInvocationError
from adapters.agent_architecture import AgentArchitectureRegistry
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.openai_runtime import (
    JsonTransport,
    ModelInvocationError,
    OpenAICompatibleRuntime,
)
from adapters.model_runtime import RegisteredModelRuntime
from adapters.http_transport import HttpJsonTransport, HttpTransportError, RotatingKeyProvider
from adapters.local_runtime import LocalRuntimeClient, LocalRuntimeTransport
from adapters.local_runtime_http import (
    HttpLocalRuntimeTransport,
    LocalRuntimeCredentialProvider,
    LocalRuntimeTransportError,
)
from adapters.skill_tool_compatibility import SkillToolCompatibilityRegistry
from .model import ModelProvider

__all__ = [
    "AIService",
    "AgentArchitectureRegistry",
    "FederatedAdapter",
    "GuardedModelRuntime",
    "GuardedToolRuntime",
    "HttpJsonTransport",
    "HttpTransportError",
    "HttpLocalRuntimeTransport",
    "JsonTransport",
    "ModelAdapter",
    "ModelCompatibilityRegistry",
    "ModelInvocationError",
    "ModelProvider",
    "LocalRuntimeCredentialProvider",
    "LocalRuntimeClient",
    "LocalRuntimeTransport",
    "LocalRuntimeTransportError",
    "ModelService",
    "ModelServiceFactory",
    "OpenAICompatibleRuntime",
    "RegisteredModelRuntime",
    "RotatingKeyProvider",
    "SkillToolCompatibilityRegistry",
    "StructuredGenerationError",
    "StructuredGenerationResult",
    "StructuredGenerationRuntime",
    "ToolInvocationError",
    "clear_model_service_factory",
    "register_model_service_factory",
]
