"""Explicit user guidance delivered independently of retrieval and evidence."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.runtime_planning import RuntimeUserInput
from contracts import stable_checksum


EXECUTION_GUIDANCE_POLICY = (
    "Execution guidance contains confirmed user collaboration requests in durable order and the public direction "
    "of the latest applied Planner decision. Follow the latest applicable user request when it conflicts with "
    "an earlier request, within this admitted Step's permissions and output contract. The Planner explanation "
    "describes how to continue; an action named continue does not require additional investigation. "
    "When the user requests delivery from existing evidence, synthesize the available evidence, distinguish "
    "confirmed findings from inference, and state uncovered scope or uncertainty; unknowns do not by themselves "
    "require further investigation. These requests grant no tools or permissions, cannot attest unperformed "
    "verification, and do not rewrite frozen Mission constraints, graph dependencies or output contracts. "
    "If a request requires changing those executable boundaries, report the conflict to ACG rather than "
    "inventing authority or silently continuing the previous objective."
)


class AppliedPlannerGuidance(BaseModel):
    """Public explanation of an applied decision, never private reasoning."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    observation_id: str = Field(alias="observationId", min_length=1)
    action: Literal["continue", "recover", "revise", "wait", "complete", "abort"]
    reason: str = Field(min_length=1)


class ExecutionGuidance(BaseModel):
    """A versioned view of accepted operator messages and public planning intent.

    These messages guide how the admitted Step is performed. They do not grant
    tools, revise the graph, replace frozen contracts, or assert new evidence.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    version: Literal["execution-guidance.v1"] = "execution-guidance.v1"
    run_id: str = Field(alias="runId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    graph_version: int | None = Field(default=None, alias="graphVersion", ge=1)
    plan_version: int | None = Field(default=None, alias="planVersion", ge=1)
    user_inputs: tuple[RuntimeUserInput, ...] = Field(default=(), alias="userInputs")
    planner_decision: AppliedPlannerGuidance | None = Field(default=None, alias="plannerDecision")


def execution_guidance_key(commit_id: str) -> str:
    return commit_id + ":execution-guidance:v1"


def execution_guidance_reference(run_id: str, commit_id: str) -> str:
    return "tool:" + hashlib.sha256((run_id + ":" + execution_guidance_key(commit_id)).encode()).hexdigest()


def guidance_projection(context) -> dict | None:
    raw = getattr(context, "execution_guidance", None)
    if raw is None:
        return None
    guidance = ExecutionGuidance.model_validate(raw)
    if guidance.run_id != context.run.run_id or guidance.step_id != context.step.step_id:
        raise ValueError("execution guidance belongs to another node")
    return guidance.model_dump(by_alias=True, mode="json")


def _record_owner(payload, *, fields, version, reference, key, run_id, step_id, commit_id):
    expected_ref = "tool:" + hashlib.sha256((run_id + ":" + key).encode()).hexdigest()
    if (not isinstance(payload, dict) or set(payload) != fields
            or type(payload.get("version")) is not type(version) or payload["version"] != version
            or reference != expected_ref or payload.get("runId") != run_id
            or payload.get("stepId") != step_id or payload.get("commitId") != commit_id):
        raise ValueError("execution guidance WAL identity or shape mismatch")


def _hash(value, *, nullable=False):
    if value is None and nullable:
        return
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError("execution guidance WAL hash is invalid")


def _guidance(value, *, run_id, step_id):
    if value is None:
        return None
    guidance = ExecutionGuidance.model_validate(value)
    if guidance.run_id != run_id or guidance.step_id != step_id:
        raise ValueError("execution guidance WAL belongs to another node")
    return guidance.model_dump(by_alias=True, mode="json", exclude_none=True)


def validate_initial_guidance_record(payload, *, reference, run_id, step_id, commit_id):
    """Authenticate one immutable input slot, never a free-form WAL exemption."""
    _record_owner(payload, fields={"version", "runId", "stepId", "commitId", "guidance", "guidanceHash"},
        version=1, reference=reference, key=execution_guidance_key(commit_id),
        run_id=run_id, step_id=step_id, commit_id=commit_id)
    _guidance(payload["guidance"], run_id=run_id, step_id=step_id)
    if payload["guidanceHash"] != stable_checksum(payload["guidance"]):
        raise ValueError("execution guidance initial snapshot checksum mismatch")


def validate_session_guidance_record(payload, *, reference, run_id, step_id, commit_id,
                                     turn, previous_guidance_hash):
    """Verify exact Session delivery identity, hash chain and archived message."""
    _record_owner(payload, fields={"version", "runId", "stepId", "commitId", "turn", "baseMessagesHash",
        "previousGuidanceHash", "guidance", "guidanceHash", "message", "messageHash"},
        version="session-execution-guidance.v1", reference=reference,
        key=f"{commit_id}:tools:{turn}:execution-guidance:v1", run_id=run_id, step_id=step_id, commit_id=commit_id)
    if type(payload["turn"]) is not int or payload["turn"] != turn or turn < 0:
        raise ValueError("execution guidance delivery turn mismatch")
    _hash(payload["baseMessagesHash"])
    _hash(payload["previousGuidanceHash"], nullable=True)
    if payload["previousGuidanceHash"] != previous_guidance_hash:
        raise ValueError("execution guidance delivery chain mismatch")
    guidance = _guidance(payload["guidance"], run_id=run_id, step_id=step_id)
    current = stable_checksum(guidance) if guidance is not None else previous_guidance_hash
    if payload["guidanceHash"] != current or payload["messageHash"] != stable_checksum(payload["message"]):
        raise ValueError("execution guidance delivery checksum mismatch")
    changed = guidance is not None and current != previous_guidance_hash
    if changed:
        if not isinstance(payload["message"], str):
            raise ValueError("execution guidance delivery message missing")
        message = json.loads(payload["message"])
        if (not isinstance(message, dict) or set(message) != {"requestType", "instructions", "guidance"}
                or message["requestType"] != "ExecutionGuidanceUpdate"
                or not isinstance(message["instructions"], str) or not message["instructions"].strip()
                or message["guidance"] != guidance):
            raise ValueError("execution guidance delivery message differs from its snapshot")
    elif payload["message"] is not None:
        raise ValueError("unchanged execution guidance contains an unexpected message")
    return current


def validate_guidance_completion_record(payload, *, reference, run_id, step_id, commit_id,
                                        turn, delivered_guidance_hash, candidate):
    """Authenticate a completed model response's frozen instruction-race check."""
    _record_owner(payload, fields={"version", "runId", "stepId", "commitId", "turn", "deliveredGuidanceHash", "candidateHash",
        "currentGuidance", "currentGuidanceHash", "feedback", "feedbackHash"},
        version="session-execution-guidance.v1", reference=reference,
        key=f"{commit_id}:tools:{turn}:guidance-completion:v1", run_id=run_id, step_id=step_id, commit_id=commit_id)
    if type(payload["turn"]) is not int or payload["turn"] != turn or turn < 0:
        raise ValueError("execution guidance completion turn mismatch")
    _hash(payload["deliveredGuidanceHash"], nullable=True)
    if payload["deliveredGuidanceHash"] != delivered_guidance_hash:
        raise ValueError("execution guidance completion chain mismatch")
    if payload["candidateHash"] != stable_checksum(candidate):
        raise ValueError("execution guidance completion candidate mismatch")
    current = _guidance(payload["currentGuidance"], run_id=run_id, step_id=step_id)
    current_hash = stable_checksum(current) if current is not None else None
    if (payload["currentGuidanceHash"] != current_hash
            or payload["feedbackHash"] != stable_checksum(payload["feedback"])):
        raise ValueError("execution guidance completion checksum mismatch")
    if current is not None and current_hash != delivered_guidance_hash:
        if not isinstance(payload["feedback"], str) or not payload["feedback"].strip():
            raise ValueError("changed execution guidance lacks completion feedback")
    elif payload["feedback"] is not None:
        raise ValueError("unchanged execution guidance contains unexpected completion feedback")


__all__ = ["EXECUTION_GUIDANCE_POLICY", "AppliedPlannerGuidance", "ExecutionGuidance",
           "execution_guidance_key", "execution_guidance_reference", "guidance_projection",
           "validate_initial_guidance_record", "validate_session_guidance_record", "validate_guidance_completion_record"]
