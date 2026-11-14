"""Watch actual provider bytes before SDK tool-call buffering and UI heartbeats."""
import asyncio
import inspect
import time

import httpx

from support.model_stream_policy import ModelStreamPolicy, ModelStreamTimeout


class ModelStreamClient(httpx.AsyncClient):
    def __init__(self, policy: ModelStreamPolicy, **kwargs):
        if 'verify' not in kwargs and kwargs.get('transport') is None:
            from app.llm.tls_context import verified_context
            kwargs['verify'] = verified_context(kwargs.get('trust_env', True))
        super().__init__(**kwargs)
        self.policy = policy
        self.on_activity = None
        self.on_context = None
        self.last_activity = 0.0
        self.request_number = 0
        self.timings = {}
        self.request_identity = {}
        self.sdk_started = None
        self.first_timings = {}

    def notify_activity(self, timings=None):
        now = time.monotonic()
        if timings:
            self.timings.update(timings)
            if self.request_number == 1:
                self.first_timings.update({'first' + key[0].upper() + key[1:]: value for key, value in timings.items()})
        if self.on_activity and (timings or now - self.last_activity >= 1):
            self.last_activity = now
            self.on_activity('model_activity', {**self.request_identity, 'providerRequest': self.request_number,
                'responseTimings': {**self.first_timings, **self.timings}} if timings else dict(self.request_identity))

    async def send(self, request, *, stream=False, **kwargs):
        started = time.monotonic()
        self.request_number += 1
        self.timings = {}
        if self.sdk_started is not None:
            self.timings['sdkRequestBuildMs'] = round((started - self.sdk_started) * 1000)
        trace_started = {}
        trace_totals = {}
        stages = {'connection.connect_tcp': 'providerConnectMs', 'connection.start_tls': 'providerTlsMs',
                  'http11.send_request_body': 'providerUploadMs', 'http2.send_request_body': 'providerUploadMs',
                  'http11.receive_response_headers': 'providerHeaderWaitMs',
                  'http2.receive_response_headers': 'providerHeaderWaitMs'}
        previous_trace = request.extensions.get('trace')

        async def trace(name, info):
            # httpcore supplies headers and network objects in info. Never retain
            # or publish them: only measure allowlisted stage boundaries.
            stage, _, boundary = name.rpartition('.')
            key = stages.get(stage)
            if key and boundary == 'started':
                trace_started[stage] = time.monotonic()
            elif key and boundary in {'complete', 'failed'} and stage in trace_started:
                trace_totals[key] = trace_totals.get(key, 0) + time.monotonic() - trace_started.pop(stage)
                self.timings[key] = round(trace_totals[key] * 1000)
            if previous_trace:
                result = previous_trace(name, info)
                if inspect.isawaitable(result):
                    await result

        request.extensions['trace'] = trace
        if self.on_context:
            self.on_context('model_context', {'requestBodyBytes': len(request.content),
                            'contextMeasurement': 'request-bytes', 'providerRequest': self.request_number,
                            **self.request_identity, 'responseTimings': dict(self.timings)})
        # Header wait is bounded separately from connecting. No tool is running
        # while an individual model HTTP request is outstanding.
        duration = min(self.policy.first_response, self.policy.total)
        try:
            async with asyncio.timeout(duration):
                response = await super().send(request, stream=True, **kwargs)
        except TimeoutError as exc:
            phase = "total" if self.policy.total <= self.policy.first_response else "first_response"
            raise ModelStreamTimeout(phase) from exc
        finally:
            if previous_trace is None:
                request.extensions.pop('trace', None)
            else:
                request.extensions['trace'] = previous_trace
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
