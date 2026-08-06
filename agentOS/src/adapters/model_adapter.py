"""模型适配器合同与应用层运行时注册边界。

本模块刻意不加载应用服务；具体模型提供方必须由应用层注册。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StructuredGenerationError(RuntimeError):
    """表示结构化模型运行时可供调用方分支处理的稳定错误。

    ``code`` 是机器可读的错误类别，异常消息供诊断展示；该异常不保存原始提示
    词或模型响应，避免把敏感输入带出运行时边界。
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StructuredGenerationResult(BaseModel):
    """向 Core 返回的安全结构化生成结果，不含原始提示词或响应。

    ``data`` 是已解析输出，提供方、模型、时延、提示词版本及用量只用于审计；
    模型冻结且禁止额外字段，调用者不能在原对象上修改其合同状态。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    data: Dict[str, Any]
    provider: str
    model: str
    latency_ms: int = Field(default=0, alias="latencyMs", ge=0)
    prompt_version: str = Field(default="native-capability.v1", alias="promptVersion")
    usage: Dict[str, Any] = Field(default_factory=dict)

    def audit_record(self) -> Dict[str, Any]:
        """提取不含生成内容的可序列化模型调用审计投影。

        返回新字典，只暴露提供方、模型、时延、提示词版本和用量副本，避免日志
        写出 prompt 或 data。该方法无副作用，固定字段故时间和空间均为 O(1)。
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "latencyMs": self.latency_ms,
            "promptVersion": self.prompt_version,
            "usage": dict(self.usage),
        }


class StructuredGenerationRuntime(Protocol):
    """定义供 ACG Agent 注入的、有资源边界的 JSON 生成运行时。

    实现负责模型访问、超时、输出解析与结构化错误映射；协议不泄漏供应商 SDK，
    也不承诺并发限制、重试或调用幂等性。
    """

    def is_available(self) -> bool:
        """返回运行时当前是否可接受生成请求。

        ``False`` 应使调用者避免发起生成；返回 ``True`` 不保证后续网络或模型
        调用必然成功。检查不改变运行时状态，线程安全语义由实现声明。
        """
        ...

    async def generate_json(
        self,
        *,
        prompt: str,
        schema: Dict[str, Any],
        thinking_mode: str = "disabled",
        timeout_seconds: float = 120.0,
        max_output_tokens: int = 4096,
        prompt_version: str = "native-capability.v1",
    ) -> StructuredGenerationResult:
        """在给定 Schema、预算和超时内生成并解析一个 JSON 结果。

        成功返回不含原始响应的 ``StructuredGenerationResult``；超时、不可用、
        JSON 无效或合同不符应抛出 ``StructuredGenerationError``。实现必须遵守
        调用者的资源参数或明确拒绝，重试与并发策略不由协议规定。
        """
        ...


class ModelService(Protocol):
    """定义 Pack 可依赖的通用文本模型服务协议。

    应用层实现负责模型选择、鉴权和网络边界；协议只约束输入文本、可选角色/上下
    文和 JSON 兼容结果，不保证流式、幂等或并发安全。
    """
    async def generate_text(
        self,
        text: str,
        role_id: Optional[str] = None,
        context: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """根据文本、可选角色和消息上下文生成结构化结果。

        返回格式由已注册实现约定；供应商异常、限流和无效上下文不得被静默吞没。
        本协议不保留历史会话状态，也不规定超时或重试策略。
        """
        ...


ModelServiceFactory = Callable[[], ModelService]

_model_service_factory: Optional[ModelServiceFactory] = None

# TODO: 在应用装配层提供带生命周期的依赖容器，替换无锁的进程级工厂；这样动态重载
# 或并发启动时不会出现工厂覆盖、客户端泄漏和首次解析竞争。


def register_model_service_factory(factory: ModelServiceFactory) -> None:
    """注册延迟创建 ``ModelService`` 的全局应用层工厂。

    后续未注入 delegate 的 ``AIService`` 会调用该工厂；新工厂覆盖旧工厂，函数
    不实例化服务。全局替换没有锁，应用启动期以外的并发注册由调用方同步。
    """
    global _model_service_factory
    _model_service_factory = factory


def clear_model_service_factory() -> None:
    """清除全局模型服务工厂，使后续延迟解析显式失败。

    已持有 delegate 的 ``AIService`` 不受影响；函数不关闭已创建客户端。全局
    状态没有锁，并发调用方需自行协调，时间与空间复杂度均为 O(1)。
    """
    global _model_service_factory
    _model_service_factory = None


class AIService:
    """为期望 ``AIService`` 的 Pack 提供兼容的延迟模型服务代理。

    可直接注入 delegate，或在首次调用时使用已注册全局工厂；工厂未注册时明确
    失败。实例缓存首次解析的 delegate，初始化与首次解析并发由调用方协调。
    """

    def __init__(self, delegate: Optional[ModelService] = None):
        self._delegate = delegate

    def _resolve_delegate(self) -> ModelService:
        if self._delegate is not None:
            return self._delegate
        if _model_service_factory is None:
            raise RuntimeError(
                "No AgentOS model service factory registered. "
                "Register one from the application layer before using AIService."
            )
        self._delegate = _model_service_factory()
        return self._delegate

    async def generate_text(
        self,
        text: str,
        role_id: Optional[str] = None,
        context: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """委托底层模型服务生成文本结果。

        输入和返回值原样遵循 ``ModelService.generate_text``；必要时先解析并缓存
        delegate。没有注入或注册服务时抛出 ``RuntimeError``，不在代理层重试。
        """
        return await self._resolve_delegate().generate_text(
            text=text,
            role_id=role_id,
            context=context,
        )


class ModelAdapter:
    """为 AgentOS Pack 提供薄的通用文本模型调用外观。

    实例持有注入服务或默认 ``AIService``，不增加缓存、重试或供应商语义；这些
    边界全部下沉至服务实现。
    """

    def __init__(self, ai_service: Optional[ModelService] = None):
        self.ai_service = ai_service or AIService()

    async def generate_text(
        self,
        text: str,
        role_id: Optional[str] = None,
        context: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """把文本、角色和上下文转交给已配置模型服务。

        成功返回服务产生的字典；配置或远端异常保持原样上抛，避免适配器伪造
        响应。该协程无本地计算，线程安全与时延由底层服务决定。
        """
        return await self.ai_service.generate_text(text=text, role_id=role_id, context=context)


__all__ = [
    "AIService",
    "ModelAdapter",
    "ModelService",
    "ModelServiceFactory",
    "StructuredGenerationError",
    "StructuredGenerationResult",
    "StructuredGenerationRuntime",
    "clear_model_service_factory",
    "register_model_service_factory",
]
