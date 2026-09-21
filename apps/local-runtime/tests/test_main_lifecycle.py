from __future__ import annotations

from runtime.main import RuntimeLifecycle


class _FakeService:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _FakeApplication:
    def __init__(self):
        self.service = _FakeService()


class _FakeServer:
    def __init__(self):
        self.shutdown_calls = 0
        self.close_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1

    def server_close(self):
        self.close_calls += 1


def test_runtime_lifecycle_shutdown_is_idempotent():
    application = _FakeApplication()
    server = _FakeServer()
    lifecycle = RuntimeLifecycle(application, server)

    lifecycle.shutdown()
    lifecycle.shutdown()

    assert server.shutdown_calls == 1
    assert server.close_calls == 1
    assert application.service.stop_calls == 1
