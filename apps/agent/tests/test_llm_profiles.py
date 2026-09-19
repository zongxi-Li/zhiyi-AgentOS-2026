"""供应商档案热切换：档案存储、双解析链路接入与管理 API。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.config import LLMConfig
from app.llm.gateway import set_llm_gateway_for_tests
from app.llm.profiles import (
    ProviderProfile,
    get_profile_store,
    resolve_active_profile,
    set_profile_store_for_tests,
)
from app.ai_engine.model_runtime import _resolve_system_provider_config

_SECRET_ENVS = (
    "GLM_API_KEY", "GLM_API_KEY_FILE",
    "DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE",
    "DASHSCOPE_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY_FILE", "QWEN_API_KEY_FILE",
)
_LLM_ENVS = ("AGENTOS_LLM_PROVIDER", "AGENTOS_LLM_BASE_URL", "AGENTOS_LLM_API_KEY", "AGENTOS_LLM_MODEL")


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_LLM_PROFILES_FILE", str(tmp_path / "llm_profiles.json"))
    for name in _LLM_ENVS + _SECRET_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GLM_API_KEY", "key-glm")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek")
    monkeypatch.setenv("TEXT_ENGINE", "glm")
    monkeypatch.setenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    monkeypatch.setenv("GLM_MODEL", "glm-5.3-flash")
    monkeypatch.delenv("QWEN_ENABLED", raising=False)
    set_profile_store_for_tests(None)
    yield monkeypatch
    set_profile_store_for_tests(None)
    set_llm_gateway_for_tests(None)


def test_bootstrap_seeds_from_env_and_keeps_env_behavior(profile_env):
    store = get_profile_store()
    data = store.load()
    names = {p.name for p in store.list_profiles()}
    assert {"glm", "glm-payg", "deepseek", "qwen"} <= names
    assert data["active"] == "glm"
    # 档案文件已落盘
    assert (store.path).exists()

    profile = resolve_active_profile()
    assert profile is not None and profile.name == "glm"
    assert profile.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"

    config = LLMConfig.from_env()
    assert config.provider == "glm"
    assert config.model == "glm-5.3-flash"


def test_switch_rebuilds_resolution_for_both_paths(profile_env):
    store = get_profile_store()
    store.set_active("deepseek")

    config = LLMConfig.from_env()
    assert config.provider == "deepseek"
    assert config.api_key == "key-deepseek"

    provider, model, base_url, api_key = _resolve_system_provider_config()
    assert provider == "deepseek"
    assert api_key == "key-deepseek"
    assert base_url == "https://api.deepseek.com/v1"
    assert model  # 默认模型名存在即可，归一化逻辑单独测试覆盖


def test_switch_to_unusable_profile_falls_back_to_env(profile_env):
    store = get_profile_store()
    store.set_active("qwen")  # qwen 无 key，档案不可用

    assert resolve_active_profile() is None
    assert LLMConfig.from_env().provider == "glm"


def test_upsert_inline_profile_and_delete_active(profile_env, tmp_path):
    store = get_profile_store()
    store.upsert(ProviderProfile(
        name="自备端点",
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        model="demo-model",
        api_key="key-inline",
    ))
    store.set_active("自备端点")

    profile = resolve_active_profile()
    assert profile is not None and profile.provider == "openai-compatible"
    assert LLMConfig.from_env().base_url == "https://api.example.com/v1"

    store.delete("自备端点")
    assert store.active_name() == ""
    assert LLMConfig.from_env().provider == "glm"


def test_profile_api_roundtrip(profile_env):
    from app.api import llm_admin

    app = FastAPI()
    app.include_router(llm_admin.router)
    client = TestClient(app)

    listing = client.get("/llm/profiles").json()
    assert listing["active"] == "glm"
    assert listing["source"] == "profile"
    assert all("api_key" not in p and "api_key_env" not in p for p in listing["profiles"])

    switched = client.post("/llm/profiles/active", json={"name": "deepseek"})
    assert switched.status_code == 200
    assert switched.json()["active"] == "deepseek"

    assert client.post("/llm/profiles/active", json={"name": "nope"}).status_code == 404

    bad = client.post("/llm/profiles", json={
        "name": "bad", "provider": "openai-compatible",
        "base_url": "ftp://x/v1", "model": "m", "api_key": "k",
    })
    assert bad.status_code == 400

    created = client.post("/llm/profiles", json={
        "name": "relay", "provider": "openai-compatible",
        "base_url": "https://api.relay.example/v1", "model": "demo", "api_key": "k-relay",
    })
    assert created.status_code == 200
    assert any(p["name"] == "relay" and p["key_source"] == "inline" for p in created.json()["profiles"])

    assert client.post("/llm/profiles/test", json={"name": "nope"}).status_code == 404
    deleted = client.delete("/llm/profiles/relay")
    assert deleted.status_code == 200
    assert all(p["name"] != "relay" for p in deleted.json()["profiles"])
