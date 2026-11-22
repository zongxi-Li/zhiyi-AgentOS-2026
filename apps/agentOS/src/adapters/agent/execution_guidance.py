"""Append confirmed execution guidance without rewriting an admitted session."""
from __future__ import annotations

import inspect
import json
from hashlib import sha256

from adapters.model.protocols import StructuredGenerationError
from adapters.model.prompt_runtime import canonical_hash
from contracts.execution_guidance import (EXECUTION_GUIDANCE_POLICY, ExecutionGuidance,
    validate_guidance_completion_record, validate_session_guidance_record)
from contracts.runtime_events import RuntimeEvent
from runtime.events.live_events import runtime_event_broker


VERSION = "session-execution-guidance.v1"
COMPLETION_FEEDBACK = (
    "Confirmed task guidance changed while this response was being generated. "
    "The updated guidance will be delivered before your next model turn. Reconcile the candidate "
    "with it using the existing evidence and output contract; do not repeat confirmed actions."
)
def guidance_message(guidance: dict) -> str:
    return json.dumps({"requestType": "ExecutionGuidanceUpdate", "instructions": EXECUTION_GUIDANCE_POLICY,
        "guidance": guidance}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SessionExecutionGuidance:
    """Per-turn delivery WAL. Confirmed model/tool history always replays first."""

    def __init__(self, context, store, commit_id):
        self.context, self.store = context, store
        self.commit_id = commit_id or context.commit_id
        self.previous_hash = None
        self.replaying_model = False
        self.guidance_protocol = False
        self.turn = None
        self.prepared = {}

    def _error(self):
        return StructuredGenerationError("EXECUTION_GUIDANCE_REPLAY_CHANGED",
            "Execution guidance differs from this session's frozen delivery")

    def _reference(self, key):
        return "tool:" + sha256((self.context.run.run_id + ":" + key).encode()).hexdigest()

    def _validate(self, value):
        if value is None:
            return None
        guidance = ExecutionGuidance.model_validate(value)
        if guidance.run_id != self.context.run.run_id or guidance.step_id != self.context.step.step_id:
            raise self._error()
        return guidance.model_dump(by_alias=True, mode="json", exclude_none=True)

    async def _read(self):
        reader = getattr(self.context, "execution_guidance_reader", None)
        value = reader() if callable(reader) else getattr(self.context, "execution_guidance", None)
        if inspect.isawaitable(value):
            value = await value
        return self._validate(value)

    async def completion_feedback(self, response=None):
        # New instructions can arrive while a paid model request is in flight.
        # Let the next settled boundary deliver them before accepting its answer.
        # Historical completions keep their original replay/validation behavior.
        store, context = self.store, self.context
        key = f"{self.commit_id}:tools:{self.turn}:guidance-completion:v1"
        saved = store.get_tool_value(run_id=context.run.run_id, key=key) if store else None
        candidate = response.get("content") if isinstance(response, dict) else getattr(response, "content", None)
        model_turn = store.get_tool_value(run_id=context.run.run_id,
            key=f"{self.commit_id}:tools:{self.turn}:model-turn") if store else None
        if model_turn is not None and isinstance(model_turn.get("response"), dict):
            # Decoder corrections are derived views. Bind delivery decisions to
            # the immutable source response that recovery can authenticate.
            candidate = model_turn["response"].get("content")
        identity = {"version": VERSION, "runId": context.run.run_id, "stepId": context.step.step_id,
            "commitId": self.commit_id, "turn": self.turn, "deliveredGuidanceHash": self.previous_hash,
            "candidateHash": canonical_hash(candidate)}
        if saved is None:
            if self.replaying_model and not self.guidance_protocol:
                return None
            current = await self._read()
            current_hash = canonical_hash(current) if current is not None else None
            feedback = COMPLETION_FEEDBACK if current is not None and current_hash != self.previous_hash else None
            saved = {**identity, "currentGuidance": current,
                "currentGuidanceHash": current_hash, "feedback": feedback, "feedbackHash": canonical_hash(feedback)}
            if store:
                store.put_tool_value(run_id=context.run.run_id, step_id=context.step.step_id, key=key,
                    payload=saved)
                saved = store.get_tool_value(run_id=context.run.run_id, key=key)
        try:
            validate_guidance_completion_record(saved, reference=self._reference(key),
                run_id=context.run.run_id, step_id=context.step.step_id, commit_id=self.commit_id,
                turn=self.turn, delivered_guidance_hash=self.previous_hash, candidate=candidate)
        except (ValueError, TypeError):
            raise self._error() from None
        return saved["feedback"]

    async def before_model(self, messages, turn):
        context, store = self.context, self.store
        key = f"{self.commit_id}:tools:{turn}:execution-guidance:v1"
        self.turn = turn
        cached = store.get_tool_value(run_id=context.run.run_id,
            key=f"{self.commit_id}:tools:{turn}:model-turn") if store else None
        self.replaying_model = cached is not None
        receipt = store.get_tool_value(run_id=context.run.run_id, key=key) if store else None
        identity = {"version": VERSION, "runId": context.run.run_id, "stepId": context.step.step_id,
            "commitId": self.commit_id, "turn": turn, "baseMessagesHash": canonical_hash(messages),
            "previousGuidanceHash": self.previous_hash}
        if receipt is None:
            # Never inject new policy into an already recorded historical turn.
            if cached is not None:
                self.guidance_protocol = False
                return None
            guidance = await self._read()
            current_hash = canonical_hash(guidance) if guidance is not None else self.previous_hash
            changed = guidance is not None and current_hash != self.previous_hash
            message = guidance_message(guidance) if changed else None
            receipt = {**identity, "guidance": guidance, "guidanceHash": current_hash,
                "message": message, "messageHash": canonical_hash(message)}
            if store:
                store.put_tool_value(run_id=context.run.run_id, step_id=context.step.step_id, key=key,
                    payload=receipt)
                receipt = store.get_tool_value(run_id=context.run.run_id, key=key)
        try:
            current_hash = validate_session_guidance_record(receipt, reference=self._reference(key),
                run_id=context.run.run_id, step_id=context.step.step_id, commit_id=self.commit_id,
                turn=turn, previous_guidance_hash=self.previous_hash)
        except (ValueError, TypeError):
            raise self._error() from None
        if receipt["baseMessagesHash"] != identity["baseMessagesHash"]:
            if not self.replaying_model:
                raise self._error()
            raise StructuredGenerationError("TOOL_REPLAY_CONTEXT_CHANGED",
                "Tool conversation replay context changed before guidance delivery")
        self.guidance_protocol = True
        guidance = self._validate(receipt.get("guidance"))
        changed = guidance is not None and current_hash != self.previous_hash
        message = receipt["message"]
        self.previous_hash = current_hash
        if not changed:
            return None
        payload = {"version": VERSION, "guidanceHash": current_hash, "turn": turn,
            "inputCount": len(guidance.get("userInputs", ())), "nodeTitle": context.step.name}
        self.prepared[turn] = payload
        await runtime_event_broker.publish(context.run.run_id, RuntimeEvent(
            eventType="execution.guidance.prepared", runId=context.run.run_id,
            nodeId=context.step.step_id, attemptId=context.attempt_id or context.commit_id,
            sequence=0, payload=payload))
        return message

    async def model_observed(self, turn):
        payload = self.prepared.pop(turn, None)
        if payload is not None:
            await runtime_event_broker.publish(self.context.run.run_id, RuntimeEvent(
                eventType="execution.guidance.delivered", runId=self.context.run.run_id,
                nodeId=self.context.step.step_id,
                attemptId=self.context.attempt_id or self.context.commit_id,
                sequence=0, payload={**payload, "replayed": self.replaying_model}))


__all__ = ["SessionExecutionGuidance", "guidance_message"]
