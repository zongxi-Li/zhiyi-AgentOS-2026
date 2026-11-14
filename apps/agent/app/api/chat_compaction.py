"""Explicit OScode projection. Original conversation records are never rewritten."""
from typing import Literal

from agents.run import ModelInputData
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai_engine.model_runtime import resolve_system_runtime_config
from app.config import settings
from app.context_compaction.runtime import CompactionBridgeError, build_input_filter, context_budget_metadata
from app.tools import get_chat_tool_runtime
from app.tools.runtime import _provider_for_model

router = APIRouter()


@router.get('/chat/context/usage')
async def get_context_usage(context_id: str, model: str = '', base_url: str = '', role_id: str | None = None):
    from app.llm.chat_session import read_context_usage
    if not base_url:
        model, base_url, _ = resolve_system_runtime_config(model)
    state = await read_context_usage(context_id, model, base_url, role_id)
    return {'contextId': context_id, 'contextUsage': state}


class CompactMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CompactRequest(BaseModel):
    context_id: str = Field(min_length=1)
    context: list[CompactMessage] = Field(default_factory=list)
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    role_id: str | None = None


@router.post("/chat/compact")
async def compact_chat(request: CompactRequest):
    if not settings.OSCODE_CONTEXT_COMPACTION_MANUAL_ENABLED:
        raise HTTPException(503, detail={"code": "COMPACTION_DISABLED", "message": "手动上下文压缩已关闭"})
    model, base_url, api_key = request.model or "", request.base_url or "", request.api_key or ""
    client = projection = None
    try:
        if not base_url and not api_key:
            model, base_url, api_key = resolve_system_runtime_config(model)
        runtime = get_chat_tool_runtime()
        context = runtime._context(request.role_id, provider=_provider_for_model(model, base_url), session_id=request.context_id)
        agent, client, metadata = runtime._build_agent(
            context, model=model, base_url=base_url, api_key=api_key,
            require_evidence=False, thinking_mode="disabled")
        projection = build_input_filter(
            agent=agent, context_id=request.context_id,
            model=str(metadata.get("effectiveModel") or model), base_url=base_url, api_key=api_key,
            model_policies=settings.OSCODE_CONTEXT_COMPACTION_MODELS)
        # Match the normal Runtime's history normalization, without appending a command turn.
        history = [{"role": item.role, "content": item.content.strip()}
                   for item in request.context if item.content.strip()]
        from app.llm.chat_session import open_chat_session
        async with open_chat_session(request.context_id, model, base_url, request.role_id, history) as session:
            projection.session = session
            source = await session.get_items() if session else history
            result = await projection.project(ModelInputData(input=source, instructions=agent.instructions), force=True)
            metrics = projection.last_metrics or {}
            changed = metrics.get('status') in {'pruned', 'summarized'}
            committed = await session.commit_projection(source, result.input, metrics) if session and changed else False
            if session and changed and not committed:
                raise ValueError('CHAT_CONTEXT_PROJECTION_STALE')
            version = session.last_view.version if session and session.last_view else 0
        return {"contextId": request.context_id, "status": metrics.get("status", "unchanged"),
                'contextUsage': session.last_view.metadata.get('contextUsage') if session and session.last_view else projection.context_usage,
                'durable': session is not None, 'projectionVersion': version,
                **context_budget_metadata(agent),
                "messages": result.input, "metrics": metrics, "model": str(metadata.get("effectiveModel") or model),
                "contextWindowTokens": projection.budget["contextWindow"]}
    except (CompactionBridgeError, ValueError) as error:
        if str(error) == 'CHAT_CONTEXT_PROJECTION_STALE':
            raise HTTPException(409, detail={'code':'CHAT_CONTEXT_PROJECTION_STALE', 'message':'历史已变化，本次投影未提交，完整记录仍保留。请重试。'}) from error
        if getattr(error,'code',None) == 'CONTEXT_HARD_LIMIT':
            raise HTTPException(422, detail={'code':'CONTEXT_HARD_LIMIT', 'message':'保护内容超过模型硬上限，无法安全压缩，请缩小当前材料。'}) from error
        raise HTTPException(422, detail={"code": "COMPACTION_CONFIG_REQUIRED",
                            "message": "压缩不可用，请检查模型窗口配置及 Node 运行环境"}) from error
    except Exception as error:
        if str(error) == 'CHAT_SESSION_BUSY':
            raise HTTPException(409, detail={'code': 'CHAT_SESSION_BUSY', 'message': '对话正在执行，请结束或取消后再压缩'}) from error
        raise HTTPException(503, detail={"code": "COMPACTION_FAILED",
                            "message": "上下文压缩失败，原始对话已保留，请稍后重试"}) from error
    finally:
        if projection is not None:
            await projection.close()
        if client is not None:
            await client.close()
