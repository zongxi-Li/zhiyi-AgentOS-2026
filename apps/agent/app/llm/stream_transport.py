"""Watch actual provider bytes before SDK tool-call buffering and UI heartbeats."""
import asyncio
import time

import httpx

from support.model_stream_policy import ModelStreamPolicy, ModelStreamTimeout


class ModelStreamClient(httpx.AsyncClient):
    def __init__(self, policy: ModelStreamPolicy, **kwargs):
        super().__init__(**kwargs)
        self.policy = policy
        self.on_activity = None
        self.on_context = None
        self.last_activity = 0.0
        self.request_number = 0
        self.timings = {}

    def notify_activity(self, timings=None):
        now = time.monotonic()
        if timings:
            self.timings.update(timings)
        if self.on_activity and (timings or now - self.last_activity >= 1):
            self.last_activity = now
            self.on_activity('model_activity', {'responseTimings': dict(self.timings)} if timings else {})

    async def send(self, request, *, stream=False, **kwargs):
        started = time.monotonic()
        self.request_number += 1
        self.timings = {}
        if self.on_context:
            self.on_context('model_context', {'requestBodyBytes': len(request.content),
                            'contextMeasurement': 'request-bytes', 'providerRequest': self.request_number})
        # Header wait is bounded separately from connecting. No tool is running
        # while an individual model HTTP request is outstanding.
        duration = min(self.policy.first_response, self.policy.total)
        try:
            async with asyncio.timeout(duration):
                response = await super().send(request, stream=True, **kwargs)
        except TimeoutError as exc:
            phase = "total" if self.policy.total <= self.policy.first_response else "first_response"
            raise ModelStreamTimeout(phase) from exc
        self.notify_activity({'providerHeadersMs': round((time.monotonic() - started) * 1000)})
        response.stream = _ModelByteStream(response.stream, self.policy, started,
            lambda first: self.notify_activity({'providerFirstByteMs': round((time.monotonic() - started) * 1000)} if first else None))
        if not stream:
            try:
                await response.aread()
            except BaseException:
                await response.aclose()
                raise
        return response


class _ModelByteStream(httpx.AsyncByteStream):
    def __init__(self, stream, policy, started, activity=None):
        self.stream, self.policy, self.started = stream, policy, started
        self.closed = False
        self.activity = activity

    async def __aiter__(self):
        iterator = self.stream.__aiter__()
        seen = False
        try:
            while True:
                remaining = self.policy.total - (time.monotonic() - self.started)
                window = self.policy.idle if seen else self.policy.first_response - (time.monotonic() - self.started)
                phase = "total" if remaining <= window else ("idle" if seen else "first_response")
                if min(remaining, window) <= 0:
                    raise ModelStreamTimeout(phase)
                try:
                    async with asyncio.timeout(min(remaining, window)):
                        chunk = await anext(iterator)
                except StopAsyncIteration:
                    return
                except TimeoutError as exc:
                    raise ModelStreamTimeout(phase) from exc
                if chunk:
                    first = not seen
                    seen = True
                    if self.activity:
                        self.activity(first)
                    yield chunk
        finally:
            await self.aclose()

    async def aclose(self):
        if not self.closed:
            self.closed = True
            await self.stream.aclose()
