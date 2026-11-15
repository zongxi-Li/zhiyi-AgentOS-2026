"""Give independently copied Permit databases their own in-process event bus."""

from contextlib import contextmanager

import pytest


@contextmanager
def isolated_runtime_events():
    from adapters import agent_tools
    from adapters.model import native
    from components.executor import node_runner
    from runtime import live_events

    broker = live_events.RuntimeEventBroker()
    # Include the existing module-level imports, so NodeRunner and model/tool
    # events use the same broker as Runtime's dynamic imports and test hooks.
    with pytest.MonkeyPatch.context() as patch:
        for module in (live_events, node_runner, agent_tools, native):
            patch.setattr(module, "runtime_event_broker", broker)
        try:
            yield broker
        finally:
            broker.flush()
