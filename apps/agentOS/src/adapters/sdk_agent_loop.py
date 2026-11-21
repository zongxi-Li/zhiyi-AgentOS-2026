"""One SDK-owned execution loop, with host-owned model/tool authority.

The headless adapter does not construct providers, resolve credentials, authorize
tools, persist sessions, or retry side effects. Its callbacks retain those ACG
responsibilities. Chat uses the same SDK runner entrypoints below.

SDK-local dispatch/completion tools adapt scheduling only. They are never sent
to a provider or included in the host's model-turn identity. The original Chat
Completions transcript stays lossless, including provider reasoning fields.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import inspect
import json
from typing import Any, Awaitable, Callable

from agents import Agent, FunctionTool, ModelSettings, RunConfig, Runner, ToolExecutionConfig
from agents.agent import ToolsToFinalOutputResult
from agents.models.interface import Model, ModelResponse
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall

from adapters.model_adapter import StructuredGenerationError


async def run_sdk_agent(*args: Any, **kwargs: Any) -> Any:
    """Shared non-streaming SDK runner; host policies remain explicit arguments."""
    # None is supported by the installed SDK. Counts are telemetry, not an
    # execution authority; completion, cancellation and host state own stopping.
    kwargs["max_turns"] = None
    return await Runner.run(*args, **kwargs)


def stream_sdk_agent(*args: Any, **kwargs: Any) -> Any:
    """Shared streaming SDK runner, preserving SDK cancellation and tool state."""
    kwargs["max_turns"] = None
    return Runner.run_streamed(*args, **kwargs)


def _field(value: Any, name: str, alias: str | None = None, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, value.get(alias, default) if alias else default)
    return getattr(value, name, default)


def _wire(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _HeadlessModel(Model):
    """Protocol adapter only; Runner owns when to call the model and tools."""

    def __init__(self, messages, tools, invoke_model, execute_tool, validate_completion, progress_feedback,
                 feedback_allowed=None, model_input_feedback=None):
        self.messages = deepcopy(messages)
        self.names = {tool["function"]["name"] for tool in tools}
        self.invoke_model = invoke_model
        self.execute_tool = execute_tool
        self.validate_completion = validate_completion
        self.progress_feedback = progress_feedback
        self.feedback_allowed = feedback_allowed
        self.model_input_feedback = model_input_feedback
        self.last_progress_feedback = None
        self.turn = 0
        self.observations: dict[str, str] = {}
        self.rejected_states: set[str] = set()
        self.failed_tool_states: set[str] = set()
        self.failed_tool_batch: list[dict[str, Any]] = []
        self.successful_observations: dict[str, Any] = {}
        self.pending: list[tuple[int, int, dict[str, Any]]] = []
        self.results: dict[tuple[int, int], str] = {}
        self.responses: dict[int, Any] = {}
        self.final_response = None
        self.failure: BaseException | None = None
        self.host_tasks: set[asyncio.Task[Any]] = set()
        self.owner_task = asyncio.current_task()

    def _assert_active(self):
        # The SDK may catch a child callback exception or cancellation. That
        # cannot reopen a failed host session or admit another paid model call.
        if self.failure is not None:
            raise self.failure
        current = asyncio.current_task()
        if any(task is not None and task.cancelling() for task in (self.owner_task, current)):
            raise asyncio.CancelledError("agent session cancellation is pending")

    def _failed_tool_feedback(self):
        if not self.failed_tool_batch:
            return
        states = {sha256(_wire({**failed, "observations": self.successful_observations}).encode("utf-8")).hexdigest()
                  for failed in self.failed_tool_batch}
        self.failed_tool_batch.clear()
        if states & self.failed_tool_states:
            raise StructuredGenerationError("AGENT_NO_PROGRESS",
                "unchanged failed tool action after corrective guidance; preserve evidence and revise unresolved work")
        self.failed_tool_states.update(states)
        self.messages.append({"role": "user", "content": (
            "A requested tool action failed. Use its error and the advertised tool schema to correct the "
            "request or choose a different supported action. Repeating the same failed action with unchanged "
            "evidence does not advance the task. Preserve all confirmed observations. When useful evidence "
            "is already available, submit the final JSON matching this node's existing output contract with "
            "the verified findings and unresolved scope so ACG can review and schedule remaining work. "
            "A failed action is not evidence that a source was read; do not claim completion of unobserved work.")})

    def _flush_results(self):
        for turn, index, call in self.pending:
            key = (turn, index)
            if key not in self.results:
                raise StructuredGenerationError("TOOL_OUTCOME_UNKNOWN", "tool result is not confirmed")
            self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                  "content": self.results.pop(key)})
        self.pending.clear()

    async def get_response(self, *args, **kwargs):
        try:
            self._assert_active()
            completed_batch = bool(self.pending)
            self._flush_results()
            turn = self.turn
            self.turn += 1
            if self.model_input_feedback is not None:
                feedback = self.model_input_feedback(deepcopy(self.messages), turn)
                if inspect.isawaitable(feedback):
                    feedback = await feedback
                self._assert_active()
                if feedback is not None:
                    if not isinstance(feedback, str) or not feedback.strip():
                        raise ValueError("model input feedback must be None or nonempty text")
                    self.messages.append({"role": "user", "content": feedback})
            if self.failed_tool_batch:
                allowed = self.feedback_allowed(deepcopy(self.messages), turn) if self.feedback_allowed else True
                if inspect.isawaitable(allowed):
                    allowed = await allowed
                self._assert_active()
                if allowed:
                    self._failed_tool_feedback()
                else:
                    # Historical WAL decisions keep their exact transcript.
                    # They were never shown this guidance, so recurrence there
                    # cannot establish that the agent ignored it.
                    self.failed_tool_batch.clear()
            if completed_batch and self.progress_feedback is not None:
                feedback = self.progress_feedback(deepcopy(self.messages), turn)
                if inspect.isawaitable(feedback):
                    feedback = await feedback
                if feedback is not None:
                    if not isinstance(feedback, str) or not feedback.strip():
                        raise ValueError("progress feedback must be None or nonempty text")
                    if feedback != self.last_progress_feedback:
                        self.messages.append({"role": "user", "content": feedback})
                        self.last_progress_feedback = feedback
            # Give the host an independent snapshot: its WAL identity must be the
            # exact input observed here, not later mutations of a shared list.
            self._assert_active()
            response = await self.invoke_model(deepcopy(self.messages), turn)
            self._assert_active()
            calls = _field(response, "tool_calls", "toolCalls", []) or []
            if calls and _field(response, "output_error", "outputError"):
                raise StructuredGenerationError("MODEL_TOOL_CALL_INVALID", "invalid final candidate includes tool calls")
            assistant = deepcopy(_field(response, "assistant_message", "assistantMessage"))
            if assistant is None:
                assistant = {"role": "assistant", "content": "" if calls else _wire(_field(response, "content", default={}))}
                if calls:
                    assistant["tool_calls"] = deepcopy(calls)
            self.messages.append(assistant)
            output = []
            if calls:
                for index, call in enumerate(calls):
                    self.pending.append((turn, index, deepcopy(call)))
                    output.append(ResponseFunctionToolCall(
                        type="function_call", id=f"dispatch_{turn}_{index}",
                        call_id=f"dispatch_{turn}_{index}", name="agentos_dispatch",
                        arguments=_wire({"turn": turn, "index": index})))
            else:
                self.responses[turn] = response
                output.append(ResponseFunctionToolCall(
                    type="function_call", id=f"completion_{turn}",
                    call_id=f"completion_{turn}", name="agentos_completion",
                    arguments=_wire({"turn": turn})))
            usage = _field(response, "usage", default={}) or {}
            return ModelResponse(output=output, usage=Usage(requests=1,
                input_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
                output_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
                total_tokens=int(usage.get("total_tokens", 0) or 0)),
                response_id=_field(response, "request_id", "requestId"))
        except BaseException as exc:
            if self.failure is None:
                self.failure = exc
            raise

    async def stream_response(self, *args, **kwargs):
        # Host invoke_model can itself stream through ACG's existing event and
        # model runtime. Starting another SDK stream would create a second owner.
        raise NotImplementedError("headless events are owned by the injected model callback")
        yield  # pragma: no cover -- Model requires an async iterator method.

    async def dispatch(self, context, arguments):
        try:
            self._assert_active()
            address = json.loads(arguments)
            turn, index = address["turn"], address["index"]
            call = next(call for t, i, call in self.pending if (t, i) == (turn, index))
            name = (call.get("function") or {}).get("name", "")
            if name not in self.names:
                result = _wire({"name": name, "source": "unknown", "status": "failed",
                                "output": {}, "error": {"code": "TOOL_ARGUMENTS_INVALID"}})
            else:
                # Runner may return on cancellation before its tool task has
                # finished unwinding. Own the host callback's lifetime so its
                # authority lease is released before this node returns. Shield
                # it from SDK teardown; close() delivers one cancellation and
                # waits for the host's cleanup instead of orphaning the effect.
                async def invoke_host():
                    try:
                        self._assert_active()
                        return await self.execute_tool(deepcopy(call), turn, index)
                    except BaseException as exc:
                        if self.failure is None:
                            self.failure = exc
                        raise

                task = asyncio.create_task(invoke_host())
                self.host_tasks.add(task)
                task.add_done_callback(self.host_tasks.discard)
                result = await asyncio.shield(task)
                if not isinstance(result, str):
                    result = _wire(result)
            self._assert_active()
            self.results[(turn, index)] = result
            function = call.get("function") or {}
            arguments = function.get("arguments")
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError):
                pass
            try:
                parsed_result = json.loads(result)
                observation = _wire(parsed_result)
            except (TypeError, ValueError):
                parsed_result = None
                observation = result
            action = _wire({"name": name, "arguments": arguments})
            self.observations[action] = observation
            error = parsed_result.get("error") if isinstance(parsed_result, dict) else None
            if isinstance(parsed_result, dict) and (parsed_result.get("status") == "failed" or error):
                self.failed_tool_batch.append({"action": action,
                    "errorCode": error.get("code") if isinstance(error, dict) else None,
                    "output": parsed_result.get("output", {})})
            else:
                # Host ToolResult.output is the business observation; transport
                # call ids and fresh receipts do not establish new evidence.
                payload = parsed_result.get("output") if isinstance(parsed_result, dict) else observation
                if isinstance(parsed_result, dict) and "output" not in parsed_result:
                    payload = {key: value for key, value in parsed_result.items() if key not in {
                        "requestId", "toolCallId", "receiptRef", "receiptChecksum", "executionId",
                        "operationId", "attemptId", "commitId", "runId", "bindingId"}}
                self.successful_observations[action] = payload
            return result
        except BaseException as exc:
            if self.failure is None:
                self.failure = exc
            raise

    async def close(self):
        for task in self.host_tasks:
            if not task.done():
                task.cancel()
        if self.host_tasks:
            await asyncio.gather(*self.host_tasks, return_exceptions=True)
        self.host_tasks.clear()

    async def check_completion(self, context, arguments):
        try:
            self._assert_active()
            response = self.responses.pop(json.loads(arguments)["turn"])
            if _field(response, "output_error", "outputError") == "MODEL_OUTPUT_INVALID_JSON":
                feedback = (
                    "Your last final answer could not be parsed as a JSON object. "
                    "Return a complete valid JSON object matching the existing output contract. "
                    "Keep the confirmed tool observations already in this conversation; "
                    "do not repeat completed actions just to correct the answer format. "
                    "Do not include Markdown fences or explanatory text outside the JSON object.")
            else:
                feedback = self.validate_completion(response) if self.validate_completion else None
                if inspect.isawaitable(feedback):
                    feedback = await feedback
            if feedback is None:
                self.final_response = response
                return "accepted"
            if not isinstance(feedback, str) or not feedback.strip():
                raise ValueError("completion validation must return None or nonempty feedback")
            error = _field(response, "output_error", "outputError")
            candidate = (_field(response, "assistant_message", "assistantMessage") or {}).get("content") if error else _field(response, "content")
            state = sha256(_wire({"candidate": candidate, "error": error, "feedback": feedback,
                                  "candidateFingerprint": (_field(response, "metadata") or {}).get("candidateFingerprint"),
                                  "observations": self.observations}).encode("utf-8")).hexdigest()
            if state in self.rejected_states:
                raise StructuredGenerationError("AGENT_NO_PROGRESS",
                    "unchanged rejected result and tool observations; acquire new evidence or revise the remaining work")
            self.rejected_states.add(state)
            # Host feedback is deliberately a follow-up input, never a new
            # system authority or an external tool observation/receipt.
            self.messages.append({"role": "user", "content": feedback})
            return "continue"
        except BaseException as exc:
            if self.failure is None:
                self.failure = exc
            raise

    def final_output(self, context, results):
        self._assert_active()
        return ToolsToFinalOutputResult(is_final_output=self.final_response is not None,
                                       final_output="accepted" if self.final_response is not None else None)


async def run_agent_loop(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                         invoke_model: Callable[[list[dict[str, Any]], int], Awaitable[Any]],
                         execute_tool: Callable[[dict[str, Any], int, int], Awaitable[str]],
                         validate_completion: Callable[[Any], Awaitable[str | None] | str | None] | None = None,
                         progress_feedback: Callable[[list[dict[str, Any]], int], Awaitable[str | None] | str | None] | None = None,
                         feedback_allowed: Callable[[list[dict[str, Any]], int], Awaitable[bool] | bool] | None = None,
                         model_input_feedback: Callable[[list[dict[str, Any]], int], Awaitable[str | None] | str | None] | None = None) -> Any:
    """Run one headless node and return its original accepted model response.

    ``invoke_model(messages, turn)`` owns model routing, WAL and diagnostics.
    ``execute_tool(raw_call, turn, index)`` owns schema validation, authorization,
    receipt verification and side-effect deduplication. Unknown tools are never
    dispatched. ``validate_completion(response)`` can return host feedback to
    continue the same Runner. Neither callbacks nor this adapter restart a node.
    ``progress_feedback(messages, turn)`` may describe host-confirmed progress
    after tool results, before the next model snapshot and its WAL identity.
    It never accepts a completion or substitutes for a tool observation.
    ``feedback_allowed(messages, turn)`` suppresses new failed-tool guidance
    while the host replays an exact historical WAL transcript. Suppressed
    guidance never registers a repeated failure as no progress.
    ``model_input_feedback(messages, turn)`` may append a host-owned instruction
    update at every settled model boundary, including the initial request. Its
    owner freezes and replays delivery before the model request is identified.
    Repeated rejected candidates with unchanged observations fail as no progress;
    new observations and corrections can continue without a turn-count ceiling.
    """
    names = [tool["function"]["name"] for tool in tools]
    if len(names) != len(set(names)):
        raise ValueError("tool wire names must be unique")
    model = _HeadlessModel(messages, tools, invoke_model, execute_tool, validate_completion, progress_feedback,
                           feedback_allowed, model_input_feedback)
    def internal_tool(name, callback, properties):
        return FunctionTool(name=name, description="Internal execution scheduling adapter.",
            params_json_schema={"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False},
            on_invoke_tool=callback, strict_json_schema=True,
            _use_default_failure_error_function=False)
    integer = {"type": "integer"}
    agent = Agent(name="Bound AgentOS executor", model=model,
        tools=[internal_tool("agentos_dispatch", model.dispatch, {"turn": integer, "index": integer}),
               internal_tool("agentos_completion", model.check_completion, {"turn": integer})],
        model_settings=ModelSettings(parallel_tool_calls=False),
        tool_use_behavior=model.final_output)
    try:
        await run_sdk_agent(agent, [],
            run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False,
                                 tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1)))
    except BaseException:
        # SDK wraps non-SDK callback errors. Preserve host error codes and
        # cancellation so unknown side effects enter the original settlement path.
        if model.failure is not None:
            raise model.failure
        raise
    finally:
        await model.close()
    # SDK's default text output contract stringifies final outputs. The host
    # receives the untouched original response, never that presentation value.
    model._assert_active()
    if model.final_response is None:
        raise StructuredGenerationError("AGENT_COMPLETION_REQUIREMENTS_UNMET", "node returned without an accepted result")
    return model.final_response


__all__ = ["run_agent_loop", "run_sdk_agent", "stream_sdk_agent"]
