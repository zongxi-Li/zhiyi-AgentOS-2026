"""Application lifespan cleanup contract, driven with injected stubs.

Importing this module's target (app.lifespan) constructs no runtime, opens no
database and starts no model adapter: the factory receives the assembly as
parameters, exactly as app.main passes the real objects.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _app_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "apps" / "agent"))


def production_settings():
    return SimpleNamespace(ENVIRONMENT="production", AI_INTERNAL_TOKEN="token-value")


class ModelSetupStub:
    def __init__(self, *, start_error=None, close_error=None):
        self.start_error = start_error
        self.close_error = close_error
        self.calls = []

    async def start(self):
        self.calls.append("model.start")
        if self.start_error:
            raise self.start_error

    async def close(self):
        self.calls.append("model.close")
        if self.close_error:
            raise self.close_error


class CoordinatorStub:
    def __init__(self, *, startup_error=None, shutdown_error=None):
        self.startup_error = startup_error
        self.shutdown_error = shutdown_error
        self.calls = []

    async def startup(self):
        self.calls.append("coordinator.startup")
        if self.startup_error:
            raise self.startup_error

    async def shutdown(self):
        self.calls.append("coordinator.shutdown")
        if self.shutdown_error:
            raise self.shutdown_error


def build_factory(**overrides):
    from app.lifespan import build_lifespan
    model = overrides.pop("model_setup", None) or ModelSetupStub()
    coordinator = overrides.pop("coordinator", None) or CoordinatorStub()
    events = []

    async def runtime_close(runtime):
        events.append("runtime_close")

    async def provider_store_close():
        events.append("provider_store_close")

    async def tool_warmup():
        events.append("tool_warmup")
        return {"tools": 1}

    def bind_planner(runtime):
        events.append("bind_planner")
        return True

    def token_check(token):
        events.append(("token_check", token))

    runtime = object()
    settings = production_settings()
    kwargs = dict(
        runtime=runtime,
        model_setup=model,
        coordinator=coordinator,
        settings=settings,
        token_check=token_check,
        tool_warmup=tool_warmup,
        bind_planner=bind_planner,
        runtime_close=runtime_close,
        provider_store_close=provider_store_close,
    )
    kwargs.update(overrides)
    return build_lifespan(**kwargs), model, coordinator, events


def run(coro):
    return asyncio.run(coro)


async def drive(lifespan, body=None):
    async with lifespan(None):
        if body is not None:
            await body()


def test_normal_startup_and_shutdown_run_every_step_in_order():
    lifespan, model, coordinator, events = build_factory()
    run(drive(lifespan))
    assert model.calls == ["model.start", "model.close"]
    assert coordinator.calls == ["coordinator.startup", "coordinator.shutdown"]
    assert events == [
        ("token_check", "token-value"),
        "tool_warmup",
        "bind_planner",
        "runtime_close",
        "provider_store_close",
    ]


def test_tool_warmup_failure_is_not_fatal():
    async def broken_warmup():
        raise RuntimeError("warmup unavailable")

    lifespan, model, coordinator, events = build_factory(tool_warmup=broken_warmup)
    run(drive(lifespan))
    assert model.calls == ["model.start", "model.close"]
    assert events == [
        ("token_check", "token-value"),
        "bind_planner",
        "runtime_close",
        "provider_store_close",
    ]


def test_token_configuration_failure_closes_assembly_and_reraises_original():
    def refusing_token_check(token):
        raise ValueError("AI_INTERNAL_TOKEN is not configured")

    lifespan, model, coordinator, events = build_factory(
        token_check=refusing_token_check)
    with pytest.raises(ValueError, match="AI_INTERNAL_TOKEN"):
        run(drive(lifespan))
    assert model.calls == ["model.close"], "unstarted assembly must still be closed"
    assert "runtime_close" in events, "the module-level Runtime must release its lock"


def test_token_failure_cleanup_error_never_masks_the_configuration_error():
    def refusing_token_check(token):
        raise ValueError("AI_INTERNAL_TOKEN is not configured")

    async def failing_runtime_close(runtime):
        raise RuntimeError("runtime close exploded")

    lifespan, model, _, events = build_factory(
        token_check=refusing_token_check, runtime_close=failing_runtime_close)
    with pytest.raises(ValueError, match="AI_INTERNAL_TOKEN"):
        run(drive(lifespan))
    assert model.calls == ["model.close"]


def test_startup_failure_closes_every_layer_and_reraises_original():
    lifespan, model, coordinator, events = build_factory(
        coordinator=CoordinatorStub(startup_error=RuntimeError("coordinator startup boom")))
    with pytest.raises(RuntimeError, match="coordinator startup boom"):
        run(drive(lifespan))
    assert model.calls == ["model.start", "model.close"]
    assert coordinator.calls == ["coordinator.startup", "coordinator.shutdown"]
    assert "runtime_close" in events


def test_model_close_failure_does_not_skip_runtime_close_nor_mask_startup_error():
    lifespan, model, coordinator, events = build_factory(
        model_setup=ModelSetupStub(start_error=RuntimeError("model start boom"),
                                   close_error=RuntimeError("model close boom")))
    with pytest.raises(RuntimeError, match="model start boom"):
        run(drive(lifespan))
    assert model.calls == ["model.start", "model.close"]
    assert "runtime_close" in events, "runtime must close even when model close fails"


def test_normal_shutdown_runs_later_steps_despite_earlier_failures():
    lifespan, model, coordinator, events = build_factory(
        coordinator=CoordinatorStub(shutdown_error=RuntimeError("coordinator shutdown boom")),
        model_setup=ModelSetupStub(close_error=RuntimeError("model close boom")))
    with pytest.raises(RuntimeError, match="coordinator shutdown boom"):
        run(drive(lifespan))
    assert model.calls == ["model.start", "model.close"], "model close still attempted"
    assert "runtime_close" in events, "runtime close still attempted"
    assert "provider_store_close" in events, "provider store close still attempted"


def test_body_exception_is_never_replaced_by_cleanup_failures():
    async def body():
        raise RuntimeError("request loop crashed")

    lifespan, model, _, events = build_factory(
        model_setup=ModelSetupStub(close_error=RuntimeError("model close boom")))
    with pytest.raises(RuntimeError, match="request loop crashed"):
        run(drive(lifespan, body))
    assert "runtime_close" in events
