"""Give independently copied Permit databases their own in-process event bus."""

from contextlib import contextmanager

import pytest


@contextmanager
def isolated_runtime_events():
    from runtime.events import live_events

    broker = live_events.RuntimeEventBroker()
    # Runtime resolves this broker when it creates NodeRunner and passes the
    # same publisher through AgentRunContext to native/model/tool adapters.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(live_events, "runtime_event_broker", broker)
        try:
            yield broker
        finally:
            broker.flush()
