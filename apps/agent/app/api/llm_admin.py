"""服务端模型供应商档案管理 API：查询 / 热切换 / 新增 / 删除 / 连通性测试。

切换只影响新请求（chat 每请求解析配置、执行链路 gateway 按 refresh 重建），
在途请求继续使用原供应商，无需重启容器。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.llm.profiles import (
    KEY_SOURCE_MISSING,
    ProviderProfile,
    get_profile_store,
)
from app.llm.gateway import get_llm_gateway

router = APIRouter()
logger = logging.getLogger(__name__)

_ALLOWED_PROVIDERS = {"deepseek", "glm", "qwen", "openai-compatible"}


class SwitchActiveRequest(BaseModel):
    name: str


class UpsertProfileRequest(BaseModel):
    name: str
    provider: str = "openai-compatible"
    base_url: str
    model: str
    api_key: str = ""
    api_key_env: str = ""


class TestProfileRequest(BaseModel):
    name: str


def _store_payload() -> Dict[str, Any]:
    store = get_profile_store()
    active = store.active_name()
    profiles: List[Dict[str, Any]] = []
    for profile in store.list_profiles():
        profiles.append(profile.to_public_dict(active=profile.name.lower() == active.lower()))
    return {
        "active": active,
        "profiles": profiles,
        "source": "profile" if any(p["active"] and p["usable"] for p in profiles) else "env",
    }


@router.get("/llm/profiles")
async def list_llm_profiles():
    """列出服务端供应商档案与当前激活项（不含任何密钥）。"""
    return _store_payload()


@router.post("/llm/profiles/active")
async def switch_llm_profile(request: SwitchActiveRequest):
    """热切换激活供应商：写档案并重建执行链路 gateway，新请求立即生效。"""
    store = get_profile_store()
    try:
        profile = store.set_active(request.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not profile.is_usable():
        raise HTTPException(
            status_code=400,
            detail=f"供应商 {profile.name} 缺少可用的 API Key 或模型配置，无法激活",
        )
    get_llm_gateway(refresh=True)
    logger.info("LLM provider switched to %s (%s/%s)", profile.name, profile.provider, profile.model)
    return _store_payload()


@router.post("/llm/profiles")
async def upsert_llm_profile(request: UpsertProfileRequest):
    """新增或更新供应商档案；密钥只落本地数据卷，响应中永不回显。"""
    name = request.name.strip()
    if not name or len(name) > 64:
        raise HTTPException(status_code=400, detail="供应商名称不能为空且不超过 64 字符")
    provider = request.provider.strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"provider 仅支持：{'、'.join(sorted(_ALLOWED_PROVIDERS))}",
        )
    base_url = request.base_url.strip()
    if not base_url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="API 地址必须是 http:// 或 https:// 开头")
    if "@" in base_url:
        raise HTTPException(status_code=400, detail="API 地址不能包含用户名或密码")
    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    profile = ProviderProfile(
        name=name,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=request.api_key.strip(),
        api_key_env=request.api_key_env.strip(),
    )
    if profile.key_source == KEY_SOURCE_MISSING:
        raise HTTPException(
            status_code=400,
            detail="未提供 API Key：请填写 api_key，或指定 api_key_env 引用服务端已有密钥变量",
        )
    get_profile_store().upsert(profile)
    return _store_payload()


@router.delete("/llm/profiles/{name}")
async def delete_llm_profile(name: str):
    store = get_profile_store()
    try:
        store.delete(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if store.active_name():
        get_llm_gateway(refresh=True)
    return _store_payload()


@router.post("/llm/profiles/test")
async def test_llm_profile(request: TestProfileRequest):
    """对指定档案发起一次轻量连通性探测（GET /models，10s 超时）。"""
    store = get_profile_store()
    matched = next(
        (p for p in store.list_profiles() if p.name.lower() == request.name.strip().lower()),
        None,
    )
    if matched is None:
        raise HTTPException(status_code=404, detail=f"供应商档案不存在: {request.name}")
    if not matched.is_usable():
        return {"ok": False, "error": "缺少可用的 API Key 或模型配置", "latency_ms": None}
    from openai import AsyncOpenAI

    started = time.perf_counter()
    client = AsyncOpenAI(
        api_key=matched.resolved_api_key(),
        base_url=matched.base_url.rstrip("/"),
        timeout=10.0,
    )
    try:
        page = await client.models.list()
        models = sorted({item.id for item in page.data if getattr(item, "id", "")})[:20]
        return {"ok": True, "models": models, "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc)[:300] or type(exc).__name__,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    finally:
        await client.close()


__all__ = ["router"]
