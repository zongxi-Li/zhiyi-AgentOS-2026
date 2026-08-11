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
from .model import ModelProvider

__all__ = [
    "AIService",
    "FederatedAdapter",
    "ModelAdapter",
    "ModelProvider",
    "ModelService",
    "ModelServiceFactory",
    "StructuredGenerationError",
    "StructuredGenerationResult",
    "StructuredGenerationRuntime",
    "clear_model_service_factory",
    "register_model_service_factory",
]
