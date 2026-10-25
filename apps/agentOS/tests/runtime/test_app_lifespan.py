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


# ---------------------------------------------------------------------------
# Cancellation safety: a cancel landing on one cleanup step must not skip the
# remaining steps, must not be swallowed, and must not mask the original
# startup error.  Cancellation is injected as the step's own exception, which
# is exactly what the event loop delivers at an await point.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cancelled_stage", ["coordinator", "model", "runtime", "provider"])
def test_cancellation_in_shutdown_runs_remaining_steps_then_reraises(cancelled_stage):
    events = []

    async def runtime_close(runtime):
        events.append("runtime_close")

    async def provider_store_close():
        events.append("provider_store_close")
        if cancelled_stage == "provider":
            raise asyncio.CancelledError()

    coordinator = CoordinatorStub(shutdown_error=asyncio.CancelledError()
                                  if cancelled_stage == "coordinator" else None)
    model = ModelSetupStub(close_error=asyncio.CancelledError()
                           if cancelled_stage == "model" else None)

    async def failing_runtime_close(runtime):
        events.append("runtime_close")
        if cancelled_stage == "runtime":
            raise asyncio.CancelledError()

    from app.lifespan import build_lifespan
    lifespan = build_lifespan(
        runtime=object(), model_setup=model, coordinator=coordinator,
        settings=production_settings(), token_check=lambda token: None,
        tool_warmup=None, bind_planner=None,
        runtime_close=failing_runtime_close if cancelled_stage == "runtime" else runtime_close,
        provider_store_close=provider_store_close)
    with pytest.raises(asyncio.CancelledError):
        run(drive(lifespan))
    assert events == ["runtime_close", "provider_store_close"], \
        "every later step must still run after the cancelled one"


def test_cancellation_during_startup_failure_cleanup_keeps_original_error():
    """The startup error wins; the cancel is logged, never able to skip steps."""
    events = []

    async def runtime_close(runtime):
        events.append("runtime_close")

    from app.lifespan import build_lifespan
    lifespan = build_lifespan(
        runtime=object(),
        model_setup=ModelSetupStub(start_error=RuntimeError("startup boom"),
                                   close_error=asyncio.CancelledError()),
        coordinator=CoordinatorStub(startup_error=RuntimeError("startup boom")),
        settings=production_settings(), token_check=lambda token: None,
        tool_warmup=None, bind_planner=None,
        runtime_close=runtime_close, provider_store_close=None)
    with pytest.raises(RuntimeError, match="startup boom"):
        run(drive(lifespan))
    assert "runtime_close" in events, "the cancelled model close must not skip the lock release"


def test_cancellation_during_token_refusal_cleanup_keeps_original_error():
    def refusing_token_check(token):
        raise ValueError("AI_INTERNAL_TOKEN is not configured")

    events = []

    async def runtime_close(runtime):
        events.append("runtime_close")

    from app.lifespan import build_lifespan
    lifespan = build_lifespan(
        runtime=object(),
        model_setup=ModelSetupStub(close_error=asyncio.CancelledError()),
        coordinator=CoordinatorStub(),
        settings=production_settings(), token_check=refusing_token_check,
        tool_warmup=None, bind_planner=None,
        runtime_close=runtime_close, provider_store_close=None)
    with pytest.raises(ValueError, match="AI_INTERNAL_TOKEN"):
        run(drive(lifespan))
    assert "runtime_close" in events


# ---------------------------------------------------------------------------
# Default dependency behaviour: the lazy-imported production seams are
# resolved at call time, so monkeypatching the owning module is observable.
# ---------------------------------------------------------------------------


def test_default_token_check_lazily_imports_and_runs_only_in_production(monkeypatch):
    import app.security.internal_auth as internal_auth
    import app.execution.wiring as wiring
    import app.llm.provider_conversation as provider_conversation
    order = []

    def recording_check(token):
        order.append(("token", token))

    async def inert_aclose(runtime):
        order.append("runtime_close")

    async def inert_provider_close():
        order.append("provider_store_close")

    monkeypatch.setattr(internal_auth, "require_valid_internal_token_configuration", recording_check)
    monkeypatch.setattr(wiring, "aclose_runtime", inert_aclose)
    monkeypatch.setattr(provider_conversation, "close_configured_provider_conversation_store",
                       inert_provider_close)
    from app.lifespan import build_lifespan

    production = production_settings()
    lifespan = build_lifespan(runtime=object(), model_setup=ModelSetupStub(),
                              coordinator=CoordinatorStub(), settings=production,
                              tool_warmup=None, bind_planner=None)
    run(drive(lifespan))
    assert order == [("token", "token-value"), "runtime_close", "provider_store_close"]

    order.clear()
    development = SimpleNamespace(ENVIRONMENT="development", AI_INTERNAL_TOKEN="token-value")
    lifespan = build_lifespan(runtime=object(), model_setup=ModelSetupStub(),
                              coordinator=CoordinatorStub(), settings=development,
                              tool_warmup=None, bind_planner=None)
    run(drive(lifespan))
    assert order == ["runtime_close", "provider_store_close"], "the token gate is production-only"


def test_default_runtime_close_and_provider_close_import_and_run_in_order(monkeypatch):
    import app.security.internal_auth as internal_auth
    import app.execution.wiring as wiring
    import app.llm.provider_conversation as provider_conversation
    order = []

    def inert_check(token):
        order.append(("token", token))

    async def recording_aclose(runtime):
        order.append(("runtime_close", runtime))

    async def recording_provider_close():
        order.append("provider_store_close")

    monkeypatch.setattr(internal_auth, "require_valid_internal_token_configuration", inert_check)
    monkeypatch.setattr(wiring, "aclose_runtime", recording_aclose)
    monkeypatch.setattr(provider_conversation, "close_configured_provider_conversation_store",
                       recording_provider_close)
    from app.lifespan import build_lifespan

    runtime = object()
    model, coordinator = ModelSetupStub(), CoordinatorStub()
    lifespan = build_lifespan(runtime=runtime, model_setup=model, coordinator=coordinator,
                              settings=production_settings(),
                              tool_warmup=None, bind_planner=None)
    run(drive(lifespan))
    assert order == [("token", "token-value"), ("runtime_close", runtime), "provider_store_close"]
    assert model.calls == ["model.start", "model.close"]
    assert coordinator.calls == ["coordinator.startup", "coordinator.shutdown"]


def test_default_runtime_close_runs_on_startup_failure(monkeypatch):
    import app.execution.wiring as wiring
    order = []

    async def recording_aclose(runtime):
        order.append("runtime_close")

    monkeypatch.setattr(wiring, "aclose_runtime", recording_aclose)
    from app.lifespan import build_lifespan

    lifespan = build_lifespan(
        runtime=object(),
        model_setup=ModelSetupStub(),
        coordinator=CoordinatorStub(startup_error=RuntimeError("startup boom")),
        settings=production_settings(), token_check=lambda token: None,
        tool_warmup=None, bind_planner=None)
    with pytest.raises(RuntimeError, match="startup boom"):
        run(drive(lifespan))
    assert order == ["runtime_close"]


def test_default_token_refusal_closes_assembly_through_default_seams(monkeypatch):
    import app.security.internal_auth as internal_auth
    import app.execution.wiring as wiring
    order = []

    def refusing_check(token):
        order.append("token_check")
        raise ValueError("AI_INTERNAL_TOKEN is not configured")

    async def recording_aclose(runtime):
        order.append("runtime_close")

    monkeypatch.setattr(internal_auth, "require_valid_internal_token_configuration", refusing_check)
    monkeypatch.setattr(wiring, "aclose_runtime", recording_aclose)
    from app.lifespan import build_lifespan

    model, coordinator = ModelSetupStub(), CoordinatorStub()
    lifespan = build_lifespan(runtime=object(), model_setup=model, coordinator=coordinator,
                              settings=production_settings(),
                              tool_warmup=None, bind_planner=None)
    with pytest.raises(ValueError, match="AI_INTERNAL_TOKEN"):
        run(drive(lifespan))
    assert order == ["token_check", "runtime_close"]
    assert model.calls == ["model.close"]
