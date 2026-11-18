"""Bounded public display projection, never an execution log or resume command.

Only narrative JSON values enter the durable projection. Provider reasoning,
tool arguments, prompts and structured completion bodies are not retained.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from time import monotonic

from contracts.runtime_events import RuntimeEvent
from contracts.task_operator_policy import public_approval_decision


_PRIVATE = re.compile(r"reasoning|chain.?of.?thought|prompt|secret|password|api[_-]?key|authorization|access[_-]?token|credential|^(?:action|arguments|parameters|tool_calls|toolCalls)$", re.I)
_NARRATIVE = frozenset("answer final_answer finalAnswer final_report report_markdown report task_summary summary overview description content text title name objective primaryGoal keyConstraints expectedArtifacts acceptanceCriteria decompositionRationale producedArtifacts analysis conclusion rationale explanation finding findings recommendation recommendations assumptions constraints success_criteria open_questions criterion result evidence unresolvedGaps unresolved_gaps risks notes".split())
_SCALARS = frozenset("agentName callId tool executionId receiptRef operationKey target resultPreview stage callKey retryIndex retryCount attempt nodeTitle model provider requestId elapsedMs idleMs receivedChunks receivedLength errorCode status taskCount dependencyCount nodeCount edgeCount requiredCapabilityCount expectedArtifactCount".split())
_WORKSPACE_REVIEW_EVENTS = frozenset({"workspace.review.blocked", "workspace.review.retry", "workspace.review.resumed"})
_WORKSPACE_REVIEW_SCALARS = frozenset({"stage", "status", "errorCode", "errorType",
    "authorityReason", "activationId", "observationId", "graphVersion"})
_NODE_TERMINAL = frozenset({"node.completed", "node.failed", "node.cancelled"})
_EVENTS = frozenset("tool.execution_started tool.execution_completed node.queued node.started model.started model.first_token model.activity model.output.delta model.completed planner.started planner.stage.started planner.stage.retry planner.model.started planner.model.first_token planner.model.activity planner.model.output.delta planner.model.completed planner.stage.completed planner.profile.resolved planner.plan.parsed planner.graph.compiled planner.completed planner.failed run.completed run.failed run.cancelled".split()) | _WORKSPACE_REVIEW_EVENTS | _NODE_TERMINAL
_TERMINAL = frozenset({"run.completed", "run.failed", "run.cancelled", "run.superseded"})


def public_narrative(raw: str) -> str:
    """Read complete and unfinished string values without guessing JSON tails."""
    source = re.sub(r"^```(?:json)?\s*", "", raw.lstrip())
    if not source.startswith(("{", "[")):
        return "" if _PRIVATE.search(source) else source
    at, parts = 0, []
    def whitespace():
        nonlocal at
        while at < len(source) and source[at].isspace():
            at += 1
    def string():
        nonlocal at
        start = at
        try:
            # The standard JSON scanner runs in C. Rewalking each cumulative
            # text character in Python would make long small-chunk streams slow.
            value, at = json.decoder.scanstring(source, at + 1, False)
            return value, True
        except ValueError:
            at = len(source)
        # Decode only a valid escaped prefix; incomplete escapes stay invisible.
        tail = source[start:at]
        for end in range(len(tail), max(0, len(tail) - 7), -1):
            try:
                value = json.loads(tail[:end] + '"')
                return re.sub(r"[\ud800-\udbff]$", "", value), False
            except (ValueError, IndexError):
                pass
        return "", False
    def read(visible=True, narrative=False, depth=0):
        nonlocal at
        whitespace()
        if at >= len(source) or depth > 24:
            return
        char = source[at]
        if char == '"':
            value, _ = string()
            if visible and narrative and value.strip():
                parts.append(value)
        elif char == "{":
            at += 1
            whitespace()
            while at < len(source) and source[at] == '"':
                key, closed = string()
                whitespace()
                if not closed or at >= len(source) or source[at] != ":":
                    return
                at += 1
                read(visible and not _PRIVATE.search(key), key in _NARRATIVE, depth + 1)
                whitespace()
                if at >= len(source) or source[at] != ",":
                    break
                at += 1
                whitespace()
            if at < len(source) and source[at] == "}":
                at += 1
        elif char == "[":
            at += 1
            whitespace()
            while at < len(source) and source[at] != "]":
                start = at
                read(visible, narrative, depth + 1)
                whitespace()
                if at == start or at >= len(source) or source[at] != ",":
                    break
                at += 1
            if at < len(source) and source[at] == "]":
                at += 1
        else:
            while at < len(source) and source[at] not in ",]} \r\n\t":
                at += 1
    try:
        read()
    except (ValueError, RecursionError):
        pass
    return "\n\n".join(parts).encode("utf-8", "replace").decode("utf-8")


class RuntimeDisplayProjection:
    """Compact replay of public display facts; bounded by calls, bytes and events."""
    def __init__(self, saved: dict | None = None):
        saved = saved or {}
        self.sequence = int(saved.get("sequence", 0))
        self.events = list(saved.get("events", []))
        self.raw: dict[str, str] = {}
        self.current: dict[str, str] = {}
        self.retired: dict[str, set[str]] = {
            key: set(values) for key, values in saved.get("retiredAttempts", {}).items()}
        self.terminal = any(e["eventType"] in _TERMINAL for e in self.events)
        self.closed: set[str] = set()
        self.pending: dict[str, RuntimeEvent] = {}
        self.folded_at: dict[str, tuple[float, int]] = {}
        for item in self.events:
            review = item["eventType"] in _WORKSPACE_REVIEW_EVENTS
            lane = "workspace_review" if review else item.get("nodeId") or "planner"
            identity = lane if review else item.get("attemptId") or str(item.get("payload", {}).get("callKey") or "planner")
            previous = self.current.get(lane)
            if item.get("nodeId") and previous and previous != identity:
                self.retired.setdefault(lane, set()).add(previous)
            self.current[lane] = identity
            if item["eventType"].endswith("model.started"):
                self.current[lane + ":call"] = item.get("displayCall", item["eventId"])

    def reopen(self, current_attempts: dict[str, str], known_attempts: dict[str, set[str]]) -> None:
        """Rebase display only after the broker has verified a durable active Run.

        Node failures remain historical facts. A previous Run terminal must not
        stop replay of a formally resumed Run, nor may its old Attempts return.
        """
        self.events = [item for item in self.events if item["eventType"] not in _TERMINAL]
        for lane, identities in known_attempts.items():
            self.retired.setdefault(lane, set()).update(identities - {current_attempts.get(lane)})
        for lane, identity in current_attempts.items():
            self.current[lane] = identity
            self.retired.setdefault(lane, set()).discard(identity)
        self.raw.clear()
        self.pending.clear()
        self.folded_at.clear()
        self.closed.clear()
        self.terminal = False
        self.sequence += 1

    def apply(self, event: RuntimeEvent) -> RuntimeEvent | None:
        self.sequence = event.sequence
        kind = event.event_type
        if kind not in _EVENTS | _TERMINAL or self.terminal:
            return None
        review = kind in _WORKSPACE_REVIEW_EVENTS
        lane = "workspace_review" if review else event.node_id or "planner"
        identity = lane if review else event.attempt_id or str(event.payload.get("callKey") or "planner")
        previous = self.current.get(lane)
        if event.node_id and identity in self.retired.get(lane, set()):
            return None
        if event.node_id and previous and previous != identity:
            self.retired.setdefault(lane, set()).add(previous)
        self.current[lane] = identity
        if kind.endswith("model.started"):
            self.raw[lane] = ""
            self.closed.discard(lane)
            self.pending.pop(lane, None)
            self.folded_at.pop(lane, None)
        source_payload = ({k: v for k, v in event.payload.items() if k in _WORKSPACE_REVIEW_SCALARS}
                          if review else event.payload)
        allowed_scalars = _WORKSPACE_REVIEW_SCALARS if review else _SCALARS
        if kind == "node.queued":
            allowed_scalars |= {"reason", "queuedAt"}
        payload = {k: (v[:1000] if isinstance(v, str) else v) for k, v in source_payload.items()
                   if k in allowed_scalars and isinstance(v, (str, int, float, bool))}
        if kind.startswith("tool.") and (approval := public_approval_decision(source_payload.get("approvalDecision"))):
            payload["approvalDecision"] = approval
        registration = source_payload.get("agentRegistration")
        if isinstance(registration, dict):
            payload["agentRegistration"] = {k: v for k, v in registration.items()
                if k in {"agentId", "instanceId", "generation"} and isinstance(v, (str, int))}
        if source_payload.get("validationFailures"):
            # The planner itself emits broker events. Import its diagnostic
            # projection only after module initialization, when an event arrives.
            from components.planner.task_decomposer import safe_validation_failures
            validation_failures = safe_validation_failures(source_payload["validationFailures"])
            if validation_failures:
                payload["validationFailures"] = validation_failures
        for collection, fields, limit in (
            ("nodes", {"key", "parentKey", "title", "objective", "capabilityId", "status", "rationale"}, 100),
            ("edges", {"sourceKey", "targetKey", "relationType"}, 300),
            ("relations", {"sourceKey", "targetKey", "relationType"}, 300),
        ):
            items = source_payload.get(collection)
            if isinstance(items, list):
                payload[collection] = [{k: v[:512] for k, v in item.items() if k in fields and isinstance(v, str)}
                                       for item in items[:limit] if isinstance(item, dict)]
        if kind.endswith("output.delta"):
            if lane in self.closed:
                return None
            # Raw structured text is ephemeral and bounded; durable/live display
            # carries the same cumulative narrative, so reconnect needs no parser prefix.
            if isinstance(event.payload.get("publicText"), str):
                payload["publicText"] = event.payload["publicText"]
            else:
                self.raw[lane] = (self.raw.get(lane, "") + str(event.payload.get("delta") or ""))[:65536]
                at, length = self.folded_at.get(lane, (0, 0))
                if monotonic() - at < .016 and len(self.raw[lane]) - length < 4096:
                    self.pending[lane] = event
                    return None
                self.pending.pop(lane, None)
                payload["publicText"] = public_narrative(self.raw[lane])
            self.folded_at[lane] = (monotonic(), len(self.raw.get(lane, "")))
        public = event.model_copy(update={"payload": payload})
        record = public.model_dump(by_alias=True, mode="json")
        # Keep start boundaries for the last 32 calls, coalesce other facts only
        # within a single call. A new attempt never overwrites its predecessor.
        if kind.endswith("model.started"):
            self.current[lane + ":call"] = event.event_id
        call = self.current.get(lane + ":call", identity)
        # Tool operations are separate records within one model turn.
        # Keep all calls, not only the last invocation of the same tool.
        if kind.startswith("tool."):
            call = str(event.payload.get("operationKey") or event.payload.get("executionId") or event.event_id)
        record["displayCall"] = call
        self.events = [e for e in self.events if not (
            e["eventType"] == kind and e.get("nodeId") == event.node_id and e.get("displayCall") == call)]
        self.events.append(record)
        calls = list(dict.fromkeys(e.get("displayCall") for e in self.events))
        keep = set(calls[-32:])
        self.events = [e for e in self.events if e.get("displayCall") in keep][-256:]
        # Old display text can be discarded; execution evidence lives elsewhere.
        length = sum(len(e.get("payload", {}).get("publicText", "")) for e in self.events)
        for old in self.events:
            if length <= 262144:
                break
            length -= len(old.get("payload", {}).pop("publicText", ""))
        self.terminal = kind in _TERMINAL
        if self.terminal:
            self.raw.clear()
            self.pending.clear()
            self.folded_at.clear()
        if kind.endswith("model.completed") or kind in _NODE_TERMINAL:
            self.raw.pop(lane, None)
            self.closed.add(lane)
        return public

    def drain_pending(self) -> list[RuntimeEvent]:
        pending, self.pending = self.pending, {}
        return [event.model_copy(update={"payload": {"publicText": public_narrative(self.raw.get(lane, ""))}})
                for lane, event in pending.items()]

    def snapshot(self, *, run=None) -> dict:
        payload = {"schemaVersion": 1, "sequence": self.sequence,
                "retiredAttempts": {key: sorted(values) for key, values in self.retired.items()},
                "events": deepcopy([{k: v for k, v in e.items() if k != "displayCall"} for e in self.events])}
        if run is not None:
            state = run.execution_state
            # Reconcile display rows with an ended task of the same identity.
            # A new attempt for this node must never inherit that outcome.
            owners = {(parts[0], attempt) for key, attempt in state.get("attemptIds", {}).items()
                      if isinstance(key, str) and isinstance(attempt, str)
                      and len(parts := key.rsplit(":", 2)) == 3}
            candidates = {(event.get("nodeId"), event.get("attemptId")) for event in self.events
                          if event.get("runId") == run.run_id and event.get("nodeId") and event.get("attemptId")}
            settled = state.get("taskSettlement", {})
            attempts = []
            for node_id, attempt_id in sorted(owners & candidates):
                task = settled.get(attempt_id) or {}
                if task.get("taskState") == "ended" and task.get("outcome") in {"failed", "cancelled"}:
                    attempts.append({"nodeId": node_id, "attemptId": attempt_id, "status": task["outcome"]})
            if attempts:
                payload["settledAttempts"] = attempts
        return payload

    def durable(self) -> dict:
        # The broker copies once under its lock before checkpoint I/O.
        return {"schemaVersion": 1, "sequence": self.sequence, "events": self.events,
                "retiredAttempts": {key: sorted(values) for key, values in self.retired.items()}}
