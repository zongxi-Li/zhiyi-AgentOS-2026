"""Provider catalog facts survive setup, Planner registration and route changes."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adapters.model.compatibility import ModelCompatibilityRegistry
from adapters.model.registered_runtime import RegisteredModelRuntime
from adapters.model.guarded import GuardedModelRuntime
from adapters.model.request_diagnostics import resolve_request_budget
from app.execution.wiring import (
    GatewayIntentLLM, RegisteredPlannerLLM, _sync_model_endpoints_from_registry,
    bind_registered_planner_llm, build_model_setup, sync_active_model_profile,
)
from app.llm.capabilities import provider_model_capabilities
from app.llm.config import LLMConfig
from components.resource.application.resource_plane import ResourcePlane
from contracts.resource import ModelEndpointProfile
from runtime.composition.app_setup import ApplicationSetupError


def runtime():
    host = SimpleNamespace(model_registry=ModelCompatibilityRegistry(), default_model_binding=None,
        resource_plane=ResourcePlane(), _intent_llm=GatewayIntentLLM())
    host.set_intent_llm = lambda model: setattr(host, "_intent_llm", model)
    return host


def configured_setup(host, *, model="deepseek-flash", base_url="https://api.deepseek.com", capabilities=None):
    entry = {"capabilityId": "model.catalog-test", "provider": "deepseek", "models": [model],
             "baseUrl": base_url, "apiKeyEnv": "TEST_KEY"}
    if capabilities is not None:
        entry["modelCapabilities"] = capabilities
    return build_model_setup(host, environment={"AGENTOS_MODELS": json.dumps([entry]), "TEST_KEY": "offline-key"})


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-chat"])
def test_initial_setup_planner_and_resource_endpoint_receive_catalog_capacity(model):
    host = runtime()
    setup = configured_setup(host, model=model)
    catalog = provider_model_capabilities(model, "https://api.deepseek.com", "deepseek")
    # Seed the old projection where tools was the only copied capability.
    host.resource_plane.store.upsert_model_endpoint(ModelEndpointProfile(
        endpointId=f"model:deepseek/{model}", provider="deepseek", model=model,
        features={"tools": True}, metadata={"_resourcePlaneSync": "model-registry"}))

    async def verify():
        await setup.start()
        try:
            assert bind_registered_planner_llm(host)
            assert isinstance(host._intent_llm, RegisteredPlannerLLM)
            capability = host._intent_llm.describe_model()
            assert capability.context_window_tokens == catalog.context_window_tokens is not None
            assert capability.max_output_tokens == catalog.max_output_tokens is not None
            assert capability.revision == catalog.version
            assert capability.max_tokens_field == catalog.max_tokens_field
            assert capability.max_tokens_required is False
            assert capability.features.tools == catalog.supports_tools
            assert capability.features.thinking == catalog.supports_thinking
            assert capability.features.json_schema == catalog.supports_json_schema
            assert resolve_request_budget(None, capability, capability.max_output_tokens) is not None
            guarded = GuardedModelRuntime(delegate=RegisteredModelRuntime(
                registry=host.model_registry, **host.default_model_binding))
            assert guarded.describe_model() == capability
            endpoint = next(item for item in host.resource_plane.model_endpoints() if item.model == model)
            assert endpoint.context_window_tokens == capability.context_window_tokens
            assert endpoint.max_output_tokens == capability.max_output_tokens
            assert endpoint.features == capability.features
            assert endpoint.version > 1  # Same tools=true must not suppress capacity repair.
        finally:
            await setup.close()

    asyncio.run(verify())


def test_gateway_promotion_uses_the_same_capability_projection(monkeypatch):
    from app.llm import gateway
    host = runtime()
    config = LLMConfig(provider="deepseek", model="deepseek-flash", base_url="https://api.deepseek.com", api_key="offline-key")
    monkeypatch.setattr(gateway, "get_llm_gateway", lambda: SimpleNamespace(
        config=config, provider_name=config.provider, model=config.model))
    setup = build_model_setup(host, environment={})

    async def verify():
        await setup.start()
        try:
            assert bind_registered_planner_llm(host)
            assert host._intent_llm.describe_model().context_window_tokens == provider_model_capabilities(
                config.model, config.base_url, config.provider).context_window_tokens
        finally:
            await setup.close()
    asyncio.run(verify())


def test_explicit_capacity_nulls_and_feature_overrides_survive_catalog_enrichment():
    host = runtime()
    explicit = {"deepseek-flash": {"contextWindowTokens": 12_000, "maxOutputTokens": None,
        "maxTokensField": "explicit_limit", "maxTokensRequired": False,
        "features": {"tools": False, "streaming": False}, "revision": "operator-profile"}}
    original = deepcopy(explicit)
    setup = configured_setup(host, capabilities=explicit)

    async def verify():
        await setup.start()
        try:
            assert bind_registered_planner_llm(host)
            caps = host._intent_llm.describe_model()
            assert caps.context_window_tokens == 12_000 and caps.max_output_tokens is None
            assert caps.max_tokens_field == "explicit_limit" and not caps.max_tokens_required
            assert caps.features.tools is False and caps.features.streaming is False
            assert caps.features.thinking is True and caps.features.json_schema is False
            assert caps.revision == "operator-profile"
            assert explicit == original
        finally:
            await setup.close()
    asyncio.run(verify())


@pytest.mark.parametrize("model,base_url", [
    ("future-deepseek-unlisted", "https://api.deepseek.com"),
    ("deepseek-flash", "https://independent-proxy.example/v1"),
])
def test_unknown_model_or_untrusted_route_does_not_inherit_official_capacity(model, base_url):
    host = runtime()
    setup = configured_setup(host, model=model, base_url=base_url)

    async def verify():
        await setup.start()
        try:
            assert bind_registered_planner_llm(host)
            caps = host._intent_llm.describe_model()
            assert caps.context_window_tokens is None and caps.max_output_tokens is None
            assert resolve_request_budget(None, caps, caps.max_output_tokens) is None
            endpoint = host.resource_plane.model_endpoints()[0]
            assert endpoint.context_window_tokens is None and endpoint.max_output_tokens is None
        finally:
            await setup.close()
    asyncio.run(verify())


def test_profile_change_updates_all_capacity_facts_but_retains_frozen_old_model_version():
    host = runtime()
    setup = configured_setup(host, base_url="https://independent-proxy.example/v1")

    async def verify():
        await setup.start()
        try:
            assert bind_registered_planner_llm(host)
            frozen = dict(host.default_model_binding)
            old_caps = RegisteredModelRuntime(registry=host.model_registry, **frozen).describe_model()
            assert old_caps.context_window_tokens is None
            config = LLMConfig(provider="deepseek", model="deepseek-flash",
                base_url="https://api.deepseek.com", api_key="new-offline-key")
            sync_active_model_profile(host, setup, config)
            current = host._intent_llm.describe_model()
            catalog = provider_model_capabilities(config.model, config.base_url, config.provider)
            assert current.context_window_tokens == catalog.context_window_tokens is not None
            assert current.max_output_tokens == catalog.max_output_tokens is not None
            assert host.default_model_binding["version"] != frozen["version"]
            assert RegisteredModelRuntime(registry=host.model_registry, **frozen).describe_model() == old_caps
            endpoint = host.resource_plane.model_endpoints()[0]
            assert endpoint.features.tools is True and endpoint.max_output_tokens == current.max_output_tokens
            assert endpoint.context_window_tokens == current.context_window_tokens
            _sync_model_endpoints_from_registry(host)
            assert host._intent_llm.describe_model() == current
        finally:
            await setup.close()
    asyncio.run(verify())


@pytest.mark.parametrize("invalid", [None, "invalid-spec"])
def test_invalid_explicit_model_capability_entry_is_not_silently_replaced(invalid):
    with pytest.raises(ApplicationSetupError):
        configured_setup(runtime(), capabilities={"deepseek-flash": invalid})
