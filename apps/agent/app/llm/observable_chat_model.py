"""Emit phase evidence before the SDK buffers complete tool arguments."""
from agents import OpenAIChatCompletionsModel
from support.cache_usage import cache_usage
from uuid import uuid4
import asyncio
import httpx
from openai import APIConnectionError
from support.model_stream_policy import ModelStreamTimeout


class ObservableChatModel(OpenAIChatCompletionsModel):
    on_progress = None
    request_number = 0
    cache_tokens = None
    on_usage = None
    on_response = None

    async def get_response(self, *args, **kwargs):
        from types import SimpleNamespace
        result = await super().get_response(*args, **kwargs)
        self.record_usage(SimpleNamespace(prompt_tokens=result.usage.input_tokens, completion_tokens=result.usage.output_tokens))
        if self.on_response:
            await self.on_response(SimpleNamespace(output=result.output, id=result.response_id))
        return result

    async def stream_response(self, *args, **kwargs):
        self.request_number += 1
        turn = self.request_number
        for retry in range(2):
            attempt_id = f"attempt_{uuid4().hex}"
            self.attempt_id = attempt_id
            if self.cache_tokens is None:
                self.cache_tokens = []
            self.cache_tokens.append(None)
            if self.on_progress:
                self.on_progress('model_phase', {'phase': 'waiting', 'turn': turn, 'attemptId': attempt_id, 'retryAttempt': retry})
            completed = False
            try:
                async for event in super().stream_response(*args, **kwargs):
                    completed |= getattr(event, 'type', '') == 'response.completed'
                    if getattr(event, 'type', '') == 'response.completed' and self.on_response:
                        await self.on_response(event.response)
                    # Runner waits for response.completed before executing this response's tools.
                    yield event.model_copy(update={'kinlin_attempt_id': attempt_id, 'kinlin_turn': turn})
                return
            except (APIConnectionError, httpx.TransportError, ModelStreamTimeout) as exc:
                if completed or retry >= 1:
                    raise
                if self.on_progress:
                    self.on_progress('model_phase', {'phase': 'retrying', 'turn': turn,
                        'attemptId': attempt_id, 'retryAttempt': retry + 1, 'errorCode': type(exc).__name__})
                # Retry only this exact model input, which already contains confirmed tool results.
                # The Runner and its completed tool calls are never restarted.
                await asyncio.sleep(0.25)

    async def _fetch_response(self, *args, **kwargs):
        result = await super()._fetch_response(*args, **kwargs)
        if not kwargs.get('stream') or not self.on_progress:
            return result
        response, stream = result
        attempt_id, turn = self.attempt_id, self.request_number
        def progress(name, data):
            self.on_progress(name, {**data, 'attemptId': attempt_id, 'turn': turn})
        return response, _ObservedChunks(stream, progress, self.record_usage)

    def record_usage(self, usage):
        context_usage = self.on_usage(usage) if self.on_usage else None
        prompt = getattr(usage, 'prompt_tokens', None)
        completion = getattr(usage, 'completion_tokens', None)
        if self.on_progress and type(prompt) is int and prompt > 0:
            # Capacity is a single model call, not the Runner's accumulated usage.
            # Publish before tools execute; a user turn can contain many calls.
            self.on_progress('model_context', {
                'contextMeasurement': 'provider-usage', 'contextInputTokens': prompt,
                'last_input_tokens': prompt,
                'last_output_tokens': completion if type(completion) is int and completion >= 0 else 0,
                'attemptId': self.attempt_id, 'turn': self.request_number,
                **({'contextUsage': context_usage} if context_usage else {}),
            })
        cached, reported = cache_usage(usage)
        if reported and self.cache_tokens:
            self.cache_tokens[-1] = cached


class _ObservedChunks:
    def __init__(self, stream, notify, usage=None):
        self.stream, self.notify = stream, notify
        self.last_tool = None
        self.usage = usage

    async def __aiter__(self):
        async for chunk in self.stream:
            if self.usage and getattr(chunk, 'usage', None) is not None:
                self.usage(chunk.usage)
            for choice in chunk.choices:
                for call in choice.delta.tool_calls or []:
                    function = call.function
                    name = getattr(function, 'name', None)
                    identity = (call.index, name or (self.last_tool[1] if self.last_tool else ''))
                    if identity != self.last_tool:
                        self.notify('model_phase', {'phase': 'tool_arguments', 'toolName': name or '',
                            **({'callId': call.id} if getattr(call, 'id', None) else {})})
                        self.last_tool = identity
            yield chunk

    async def aclose(self):
        close = getattr(self.stream, 'aclose', None) or getattr(self.stream, 'close', None)
        if close:
            await close()
