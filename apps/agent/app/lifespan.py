"""FastAPI application lifespan with fail-closed assembly cleanup.

Split from ``app.main`` so the startup/shutdown cleanup contract is testable
with injected stubs: importing this module constructs no runtime, opens no
database and starts no model adapter.  ``app.main`` injects the module-level
assembly exactly as tests inject doubles.

Cleanup contract:

* A startup refusal (production token configuration) or a startup failure
  closes every already-constructed layer - coordinator, model setup, runtime
  - and re-raises the ORIGINAL error; cleanup failures are logged, never
  allowed to mask it.
* Normal shutdown awaits every step even when earlier steps fail, in reverse
  construction order, and surfaces the first cleanup failure only after all
  steps ran - and never replaces an in-flight exception from the served body.
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)


async def run_cleanups(steps: Sequence[tuple[str, Callable[[], Awaitable[None]]]]) -> list[BaseException]:
    """Await every step even when earlier ones fail; collect, log, continue."""
    failures: list[BaseException] = []
    for name, step in steps:
        try:
            await step()
        except Exception as exc:
            logger.warning("lifespan cleanup step failed: %s (%s)",
                           name, type(exc).__name__, exc_info=True)
            failures.append(exc)
    return failures


def build_lifespan(
    *,
    runtime: Any,
    model_setup: Any,
    coordinator: Any,
    settings: Any,
    token_check: Callable[[str], None] | None = None,
    tool_warmup: Callable[[], Awaitable[Any]] | None = None,
    bind_planner: Callable[[Any], bool] | None = None,
    runtime_close: Callable[[Any], Awaitable[None]] | None = None,
    provider_store_close: Callable[[], Awaitable[None]] | None = None,
):
    """Compose the application lifespan around an already-built assembly."""
    if token_check is None:
        from app.security.internal_auth import require_valid_internal_token_configuration

        def token_check(token: str) -> None:
            require_valid_internal_token_configuration(token)

    if runtime_close is None:
        async def runtime_close(target: Any) -> None:  # noqa: F811 - seam default
            from app.execution.wiring import aclose_runtime
            await aclose_runtime(target)

    if provider_store_close is None:
        async def provider_store_close() -> None:  # noqa: F811 - seam default
            from app.llm.provider_conversation import close_configured_provider_conversation_store
            await close_configured_provider_conversation_store()

    async def close_assembly(first_step: str | None) -> list[BaseException]:
        steps: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        if first_step is not None:
            steps.append((first_step, coordinator.shutdown))
        steps.append(("model_setup.close", model_setup.close))
        steps.append(("runtime.aclose", lambda: runtime_close(runtime)))
        return await run_cleanups(steps)

    @asynccontextmanager
    async def lifespan(app: Any):
        production = str(settings.ENVIRONMENT).strip().lower() in {"prod", "production"}
        try:
            if production:
                token_check(settings.AI_INTERNAL_TOKEN)
        except BaseException:
            # Refused before any service started; the module-level assembly
            # still owns the instance lock and its stores.  Cleanup failures
            # must not mask the original configuration error.
            await close_assembly(first_step=None)
            raise
        if tool_warmup is not None:
            try:
                warmup = await tool_warmup()
                logger.info("Read-only tool runtime ready: %s", warmup)
            except Exception as exc:
                logger.warning("Read-only tool runtime warmup failed: %s", type(exc).__name__)
        try:
            await model_setup.start()
            if bind_planner is not None and bind_planner(runtime):
                logger.info(
                    "Planner model streaming bound to the Runtime-owned model registry")
            await coordinator.startup()
        except BaseException:
            await close_assembly(first_step="coordinator.shutdown")
            raise
        try:
            yield
        finally:
            failures = await run_cleanups((
                ("coordinator.shutdown", coordinator.shutdown),
                ("model_setup.close", model_setup.close),
                ("runtime.aclose", lambda: runtime_close(runtime)),
                ("provider_store_close", provider_store_close),
            ))
            if failures and sys.exc_info()[0] is None:
                # Surface the earliest cleanup failure only after every step
                # ran; an in-flight exception from the served body wins.
                raise failures[0]

    return lifespan


__all__ = ["build_lifespan", "run_cleanups"]
