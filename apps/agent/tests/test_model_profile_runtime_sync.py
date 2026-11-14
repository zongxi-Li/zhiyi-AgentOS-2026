"""Provider updates reach the production ACG registry, planner and resource plane."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.http_transport import HttpJsonTransport
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from components.resource.application.resource_plane import ResourcePlane
from runtime.app_setup import ApplicationSetup
from app.execution.wiring import (
    GatewayIntentLLM, RegisteredPlannerLLM, bind_registered_planner_llm,
    sync_active_model_profile,
)
from app.llm.config import LLMConfig
from app.llm.gateway import set_llm_gateway_for_tests
from app.llm.profiles import get_profile_store, set_profile_store_for_tests


def runtime_and_setup():
    runtime = SimpleNamespace(
        model_registry=ModelCompatibilityRegistry(), default_model_binding=None,
        resource_plane=ResourcePlane(), _intent_llm=GatewayIntentLLM(),
    )
    runtime.set_intent_llm = lambda planner: setattr(runtime, "_intent_llm", planner)
    return runtime, ApplicationSetup.from_environment({}, model_registry=runtime.model_registry)


def config(provider="glm", *, base_url="https://glm.example/v4", key="key-old"):
    return LLMConfig(provider=provider, model="glm-5.3-flash" if provider == "glm" else "deepseek-chat",
                     base_url=base_url, api_key=key)


def test_switch_registers_new_route_and_preserves_frozen_endpoint_and_credentials(monkeypatch):
    runtime, setup = runtime_and_setup()
    requests = []

    async def post(transport, *, path, payload, **kwargs):
        requests.append((transport._base_url, transport._key_provider.current_key(), payload["model"]))
        return {"choices": [{"message": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}]}

    monkeypatch.setattr(HttpJsonTransport, "post_json", post)

    async def verify():
        await setup.start()  # A process with no initial model can be configured later.
        sync_active_model_profile(runtime, setup, config())
        frozen = dict(runtime.default_model_binding)
        old_adapter = runtime.model_registry.resolve(**frozen)
        assert isinstance(runtime._intent_llm, RegisteredPlannerLLM)
        assert setup._health_task is not None
        task = setup._health_task

        sync_active_model_profile(runtime, setup, config(base_url="https://glm-new.example/v4", key="key-new"))
        assert runtime.default_model_binding["version"] != frozen["version"]
        assert runtime.model_registry.resolve(**frozen) is old_adapter
        assert setup._health_task is task
        for binding in (frozen, runtime.default_model_binding):
            model = RegisteredModelRuntime(registry=runtime.model_registry, **binding)
            result = await model.generate_json(prompt="test", schema={"type": "object"})
            assert result.data == {"answer": "ok"}
        assert requests == [
            ("https://glm.example/v4", "key-old", "glm-5.3-flash"),
            ("https://glm-new.example/v4", "key-new", "glm-5.3-flash"),
        ]
        sync_active_model_profile(runtime, setup, config("deepseek"))
        assert runtime._intent_llm.provider == "deepseek"
        assert {r["provider"] for r in runtime._intent_llm.copilot_models()} == {"glm", "deepseek"}
        endpoints = runtime.resource_plane.model_endpoints()
        assert {e.provider for e in endpoints} == {"glm", "deepseek"}
        assert all(e.model_version for e in endpoints)
        await setup.close()
        assert task.done()

    asyncio.run(verify())


def test_startup_projects_models_after_adapter_registration():
    import json
    runtime, _ = runtime_and_setup()
    setup = ApplicationSetup.from_environment({"KEY": "key-test", "AGENTOS_MODELS": json.dumps([{
        "capabilityId": "model.startup", "provider": "glm", "models": ["glm-5.3-flash"],
        "baseUrl": "https://glm.example/v4", "apiKeyEnv": "KEY",
    }])}, model_registry=runtime.model_registry)
    runtime.default_model_binding = setup.default_model_binding
    assert not runtime.resource_plane.model_endpoints()

    async def verify():
        await setup.start()
        try:
            assert bind_registered_planner_llm(runtime)
            assert runtime.resource_plane.model_endpoints()[0].model == "glm-5.3-flash"
        finally:
            await setup.close()
    asyncio.run(verify())


@pytest.fixture
def profile_client(tmp_path, monkeypatch):
    from app.api import llm_admin
    for name in ("AGENTOS_LLM_PROVIDER", "AGENTOS_LLM_BASE_URL", "AGENTOS_LLM_API_KEY", "AGENTOS_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTOS_LLM_PROFILES_FILE", str(tmp_path / "profiles.json"))
    monkeypatch.setenv("GLM_API_KEY", "key-glm")
    monkeypatch.setenv("GLM_BASE_URL", "https://glm.example/v4")
    monkeypatch.setenv("GLM_MODEL", "glm-5.3-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-deepseek")
    monkeypatch.setenv("TEXT_ENGINE", "glm")
    set_profile_store_for_tests(None)
    app = FastAPI()
    app.include_router(llm_admin.router)
    runtime, setup = runtime_and_setup()
    app.state.sync_llm_profile = lambda cfg: sync_active_model_profile(runtime, setup, cfg)
    yield TestClient(app), runtime, app
    set_profile_store_for_tests(None)
    set_llm_gateway_for_tests(None)


def test_profile_api_switch_and_active_edit_synchronize_acg(profile_client):
    client, runtime, app = profile_client
    response = client.post("/llm/profiles/active", json={"name": "glm"})
    assert response.status_code == 200
    assert runtime.default_model_binding["provider"] == "glm"
    assert runtime._intent_llm.model == "glm-5.3-flash"
    response = client.post("/llm/profiles", json={
        "name": "glm", "provider": "glm", "model": "glm-5.3",
        "base_url": "https://new.example/v4", "api_key": "key-edited",
    })
    assert response.status_code == 200
    assert runtime.default_model_binding["model"] == "glm-5.3"
    assert "key-edited" not in response.text
    assert client.post("/llm/profiles/active", json={"name": "deepseek"}).status_code == 200
    assert runtime._intent_llm.provider == "deepseek"
    assert client.delete("/llm/profiles/deepseek").status_code == 200
    assert runtime._intent_llm.provider == "glm"  # Deleted active profile falls back to TEXT_ENGINE.


def test_failed_sync_and_unusable_profile_leave_previous_active_configuration(profile_client):
    client, runtime, app = profile_client
    assert client.post("/llm/profiles/active", json={"name": "glm"}).status_code == 200
    binding = dict(runtime.default_model_binding)

    def fail(cfg):
        raise RuntimeError("must-not-leak-key")
    app.state.sync_llm_profile = fail
    response = client.post("/llm/profiles/active", json={"name": "deepseek"})
    assert response.status_code == 503
    assert "must-not-leak-key" not in response.text
    assert get_profile_store().active_name() == "glm"
    assert runtime.default_model_binding == binding
    store = get_profile_store()
    from app.llm.profiles import ProviderProfile
    store.upsert(ProviderProfile(name="empty", provider="glm", base_url="https://empty.example", model="m"))
    assert client.post("/llm/profiles/active", json={"name": "empty"}).status_code == 400
    assert store.active_name() == "glm"


def test_invalid_active_endpoint_rolls_back_without_rebinding(profile_client):
    client, runtime, _ = profile_client
    assert client.post("/llm/profiles/active", json={"name": "glm"}).status_code == 200
    binding = dict(runtime.default_model_binding)
    response = client.post("/llm/profiles", json={
        "name": "glm", "provider": "glm", "model": "glm-5.3-flash",
        "base_url": "http://insecure.example/v4", "api_key": "key-invalid",
    })
    assert response.status_code == 503
    assert "key-invalid" not in response.text
    assert get_profile_store().active_profile().base_url == "https://glm.example/v4"
    assert runtime.default_model_binding == binding
