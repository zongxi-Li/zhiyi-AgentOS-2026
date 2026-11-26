"""Bind a node to the accepted operator inbox without sharing mutable sessions."""
from __future__ import annotations

from copy import deepcopy
from itertools import chain
import json

from contracts import stable_checksum
from contracts.execution_guidance import (AppliedPlannerGuidance, ExecutionGuidance, execution_guidance_key,
    execution_guidance_reference, validate_initial_guidance_record, validate_session_guidance_record)
from contracts.runtime_planning import RuntimeUserInput


def build_execution_guidance(run, step_id: str, *, pending_inputs=()) -> dict | None:
    """Project trusted stored inputs, retaining their durable order and identity.

    The inbox contains authenticated, confirmed collaboration operations. Its
    inputs may steer an active Step before the next Planner boundary, while
    permissions and executable contracts remain owned by their existing gates.
    """
    loop = run.execution_state.get("planningLoop") or {}
    inputs, known = [], {}
    for raw, inbox in chain(((item, False) for item in loop.get("userInputs", ())),
                            ((item, True) for item in pending_inputs)):
        item = RuntimeUserInput.model_validate(raw)
        if inbox and item.source_run_id != run.run_id:
            raise ValueError("execution guidance inbox belongs to another Run")
        identity = (item.source_run_id, item.operation_id)
        if identity in known:
            if known[identity] != item:
                raise ValueError("execution guidance input identity conflict")
            continue
        known[identity] = item
        inputs.append(item)
    current = loop.get("current") or {}
    decision = current.get("decision") or {}
    planning = None
    if current.get("status") == "applied" and decision:
        if current.get("observationId") != decision.get("observationId"):
            raise ValueError("execution guidance decision observation mismatch")
        planning = AppliedPlannerGuidance.model_validate({
            key: decision[key] for key in ("observationId", "action", "reason")})
    if not inputs and planning is None:
        return None
    state = run.execution_state
    return ExecutionGuidance(runId=run.run_id, stepId=step_id,
        graphVersion=state.get("graphVersion"), planVersion=state.get("taskPlanVersion"),
        userInputs=tuple(inputs), plannerDecision=planning).model_dump(by_alias=True, mode="json")


def bind_execution_guidance(*, workflow_store, run, step_id: str, commit_id: str, value_store,
                           legacy_execution: bool = False):
    """Freeze initial delivery and return a reader bound to this exact node.

    A later call reads the independent inbox rather than a live Runner's stale
    Run copy. Session code seals individual delivery boundaries in its own WAL;
    this helper does not change an already admitted prompt or model-turn hash.
    """
    run_id, mission_id = run.run_id, run.mission_id
    graph_version = run.execution_state.get("graphVersion")

    def read():
        current = workflow_store.get_run(run_id) if workflow_store is not None else run
        if (current.run_id != run_id or current.mission_id != mission_id
                or current.execution_state.get("graphVersion") != graph_version
                or (workflow_store is not None and not any(step.step_id == step_id for step in current.steps))):
            raise ValueError("execution guidance reader no longer owns the admitted node")
        inputs = workflow_store.list_planning_inputs(run_id) if workflow_store is not None else ()
        return build_execution_guidance(current, step_id, pending_inputs=inputs)

    key = execution_guidance_key(commit_id)
    saved = value_store.get_tool_value(run_id=run_id, key=key)
    if saved is None:
        # Pre-protocol executions preserve their original initial request;
        # their live reader can still supply an appended Session update.
        guidance = None if legacy_execution else read()
        saved = {"version": 1, "runId": run_id, "stepId": step_id, "commitId": commit_id,
                 "guidance": guidance, "guidanceHash": stable_checksum(guidance)}
        value_store.put_tool_value(run_id=run_id, step_id=step_id, key=key, payload=saved)
    if (set(saved) != {"version", "runId", "stepId", "commitId", "guidance", "guidanceHash"}
            or saved["version"] != 1 or saved["runId"] != run_id or saved["stepId"] != step_id
            or saved["commitId"] != commit_id or saved["guidanceHash"] != stable_checksum(saved["guidance"])):
        raise ValueError("execution guidance snapshot identity mismatch")
    if saved["guidance"] is not None:
        guidance = ExecutionGuidance.model_validate(saved["guidance"])
        if guidance.run_id != run_id or guidance.step_id != step_id or guidance.graph_version != graph_version:
            raise ValueError("execution guidance snapshot belongs to another node")
    return deepcopy(saved["guidance"]), read


def read_undispatched_guidance_inputs(connection, *, run, node):
    """Authenticate the only guidance writes allowed before a first response.

    This is input authentication, not a no-dispatch proof. The caller still
    closes the complete activity ledger and rejects model/tool admissions.
    """
    import hashlib

    result = {}
    initial_key = execution_guidance_key(node.operation_id)
    keys = (initial_key, f"{node.operation_id}:tools:0:execution-guidance:v1")
    for key in keys:
        reference = "tool:" + hashlib.sha256((run.run_id + ":" + key).encode()).hexdigest()
        row = connection.execute("SELECT run_id,step_id,kind,operation_id,payload_json FROM execution_values WHERE reference=?",
            (reference,)).fetchone()
        if row is None:
            continue
        if tuple(row[:4]) != (run.run_id, node.step_id, "output", None):
            raise ValueError("execution guidance input has another ledger owner or kind")
        from .value_storage import decode_body
        payload = decode_body(connection, run_id=run.run_id, reference=reference, encoded=row[4])
        if key == initial_key:
            validate_initial_guidance_record(payload, reference=reference,
                run_id=run.run_id, step_id=node.step_id, commit_id=node.operation_id)
        else:
            validate_session_guidance_record(payload, reference=reference, run_id=run.run_id,
                step_id=node.step_id, commit_id=node.operation_id, turn=0, previous_guidance_hash=None)
        result[reference] = payload
    linked = getattr(node, "artifact_refs", {}).get("executionGuidance")
    if linked is not None and (linked != execution_guidance_reference(run.run_id, node.operation_id) or linked not in result):
        raise ValueError("execution guidance input reference is missing or misaddressed")
    return result


__all__ = ["build_execution_guidance", "bind_execution_guidance", "read_undispatched_guidance_inputs"]
