"""Run-scoped diagnostic context snapshots, separate from execution evidence.

Only persisted task content and known host envelopes are projected. Credentials,
provider internals and unrelated Runs are never a source for this catalog.
"""
from __future__ import annotations

from copy import deepcopy

from components.communicator.contracts import ContextPack, estimate_tokens
from components.executor.memory_input import memory_retrieval_key, validate_memory_retrieval_snapshot
from adapters.model.native_prompt import NativeCapabilityPromptBuilder
from contracts import stable_checksum
from contracts.planning_context import PLANNING_CONTEXT_METADATA_FIELD, PLANNING_CONTEXT_OWNER, planning_context_key
from contracts.mission_semantic import run_intent_basis
from contracts.memory import MemoryType
from contracts.runtime_planning import PlanningContextIndexEntry, PlanningResultField, RuntimePlanningState
from contracts.workflow import utc_now
from contracts.tools import ToolResult
from runtime.planner_input_adapter import material_input
from runtime.planning_results import _encoded_size


_IDENTITY = ("runId", "stepId", "attemptId", "commitId")
_TOOL_RECORD = (*_IDENTITY, "tool", "status", "errorCode", "executionId", "resourceId", "bindingId",
    "requestRef", "receiptRef", "receiptChecksum", "workspaceId", "grantId")
_STEP_INPUT = ("from", "prefetch", "schema", "workset", "contextPolicy", "memoryPolicy")


def _pick(value, fields):
    return {field: deepcopy(value[field]) for field in fields if field in value} if isinstance(value, dict) else {}


def _tool_output(value):
    if value is not None and not isinstance(value, dict):
        raise ValueError("saved tool business output must be an object")
    return deepcopy(value) if value is not None else {}


def _model_calls(calls):
    result = []
    for call in calls if isinstance(calls, list) else ():
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else call
        result.append({**_pick(call, ("id", "type")), "name": function.get("name"),
            "arguments": deepcopy(function.get("arguments"))})
    return result


def _tool_snapshot(payload, run_id, step_id):
    """Known WAL envelopes only; arbitrary tool metadata is not model context."""
    if not isinstance(payload, dict):
        raise ValueError("saved tool context must be an object")
    request, identity = payload.get("request"), payload.get("identity")
    if not isinstance(identity, dict) and payload.get("runId") == run_id and payload.get("stepId") == step_id:
        identity = payload
    if isinstance(request, dict) and isinstance(identity, dict):
        if identity.get("runId") != run_id or identity.get("stepId") != step_id:
            return None
        data = {"identity": _pick(identity, _IDENTITY), "request": {
            **_pick(request, ("protocolVersion", "requestId", "invocationId", "resourceId", "capabilityId", "idempotencyKey")),
            "input": deepcopy(request.get("input") or {}),
            "workspace": _pick(request.get("authorization"), ("workspaceId", "grantId"))}}
        return "tool_request", "admitted", "host_recorded", data
    record = payload.get("record")
    if isinstance(record, dict) and record.get("runId") == run_id and record.get("stepId") == step_id:
        return "tool_result", str(record.get("status") or "recorded"), "tool_observation", {
            "record": _pick(record, _TOOL_RECORD), "output": _tool_output(payload.get("data"))}
    if isinstance(identity, dict) and identity.get("runId") == run_id and identity.get("stepId") == step_id:
        if isinstance(payload.get("result"), dict) and payload.get("retrievalRequestHash"):
            result = payload["result"]
            if stable_checksum(result) != payload.get("resultHash"):
                raise ValueError("saved retrieval result checksum changed")
            return "retrieval_result", "recorded", "retrieved_content", {
                "identity": _pick(identity, _IDENTITY),
                **_pick(payload, ("retrievalRequestHash", "resultHash")),
                "result": {**_pick(result, ("text", "model")),
                    "sources": [_pick(source, ("id", "citationId", "title", "filename", "url", "uri", "snippet", "content",
                        "provider", "retrievedAt", "manifestId")) for source in result.get("sources") or ()],
                    "toolExecutions": [_pick(item, ("tool", "name", "toolName", "callId", "status", "durationMs",
                        "inputSummary", "outputSummary", "sourceRefs", "errorCode", "executionId", "provider"))
                        for item in result.get("toolExecutions") or ()]}}
        if payload.get("version") == "native-retrieval.v1" and payload.get("tool"):
            return "retrieval_request", "admitted", "host_recorded", _pick(payload,
                ("version", "identity", "tool", "callHash"))
        if isinstance(payload.get("output"), dict) and payload.get("status"):
            return "tool_receipt", str(payload["status"]), "tool_observation", {
                **_pick(payload, ("protocolVersion", "requestId", "invocationId", "capabilityId", "grantId",
                    "idempotencyKey", "status", "startedAt", "completedAt", "checksum")),
                "identity": _pick(identity, _IDENTITY), "output": _tool_output(payload["output"]),
                "error": _pick(payload.get("error"), ("code", "retryable"))}
        if payload.get("executionId") or payload.get("reason"):
            return "tool_settlement", "unsettled" if payload.get("reason") else "admitted", "host_recorded", {
                **_pick(payload, (*_IDENTITY, "executionId", "leaseId", "resourceId", "reason",
                    "reconciliationReason", "quarantineScope"))}
    response = payload.get("response")
    if payload.get("requestHash") and isinstance(response, dict):
        # Assistant text and declared actions are saved public session outputs;
        # reasoning/provider metadata and transport headers are intentionally absent.
        message = response.get("assistantMessage") or {}
        return "model_turn", "candidate", "agent_generated", {
            "requestHash": payload["requestHash"],
            "response": {**_pick(response, ("requestId", "content", "outputError", "provider", "model")),
                "assistantMessage": _pick(message, ("role", "content")),
                "toolCalls": _model_calls(response.get("toolCalls"))}}
    if all(field in payload for field in ("name", "source", "status", "output")):
        result = ToolResult.model_validate(payload)
        return "agent_tool_result", result.status, "tool_observation", {
            "name": result.name, "source": result.source, "status": result.status,
            "output": deepcopy(result.output), "error": _pick(result.error, ("code", "retryable"))}
    return None


def build_planning_context_catalog(services, run, *, workspace_snapshot=None):
    """Seal this observation's available context without exporting whole bodies."""
    store = services.execution_value_store
    entries, seen = [], set()

    def add(kind, title, data, *, status="available", trust="host_recorded", step_id=None,
            attempt_id=None, operation_id=None, original_ref=None):
        metadata = {"version": 1, "runId": run.run_id, "contextKind": kind, "sourceRunId": run.run_id,
            "stepId": step_id, "attemptId": attempt_id, "operationId": operation_id,
            "originalRef": original_ref, "status": status, "trust": trust}
        body = {**deepcopy(data), PLANNING_CONTEXT_METADATA_FIELD: metadata}
        checksum = stable_checksum(body)
        if checksum in seen:
            return
        seen.add(checksum)
        reference = store.put_tool_value(run_id=run.run_id, step_id=PLANNING_CONTEXT_OWNER,
            key=planning_context_key(body), payload=body)
        fields = tuple(PlanningResultField(name=field, present=True, valueType=type(value).__name__,
            byteLength=_encoded_size(value), estimatedTokens=estimate_tokens({field: value}),
            itemCount=len(value) if isinstance(value, (list, dict)) else None)
            for field, value in sorted(data.items()))
        entries.append(PlanningContextIndexEntry(contextRef=reference, contextKind=kind, title=title,
            sourceRunId=run.run_id, stepId=step_id, attemptId=attempt_id, operationId=operation_id,
            originalRef=original_ref, status=status, trust=trust, checksum=checksum,
            byteLength=_encoded_size(data), estimatedTokens=estimate_tokens(data), fields=fields))

    def unavailable(kind, title, error, **identity):
        add(kind, title, {"error": {"code": "CONTEXT_SNAPSHOT_INVALID", "exceptionType": type(error).__name__}},
            status="unavailable", trust="diagnostic", **identity)

    basis = run_intent_basis(run)
    if basis is not None:
        add("mission_intent", "Frozen Mission intent", {"intent": basis.model_dump(by_alias=True, mode="json")},
            trust="caller_intent")
    mission = services.workflow_store.get_mission(run.mission_id)
    add("task_request", "Original task request", {"missionId": run.mission_id, "title": mission.title,
        "domain": mission.domain, "intent": mission.intent,
        "request": _pick(run.input, ("objective", "userIntent", "taskGoal", "intent", "title", "goal", "constraints"))},
        trust="caller_supplied")
    # Explicit content channels match the existing native prompt boundary.
    materials = NativeCapabilityPromptBuilder._task_source_data(material_input(run.input))
    materials.update(_pick(run.input, ("attachmentIds", "materialRefs", "inputAttachmentIds")))
    if materials:
        add("task_materials", "Task supplied materials", materials, trust="caller_supplied")
    if workspace_snapshot is None:
        from runtime.workspace_planning_context import workspace_discovery_snapshot
        workspace_snapshot = workspace_discovery_snapshot(run, store)
    if workspace_snapshot and workspace_snapshot.get("contextRef"):
        from runtime.workspace_planning_context import load_workspace_discovery_materials
        from components.planner.workspace_discovery import workspace_planning_material
        from types import SimpleNamespace
        observation = SimpleNamespace(run_id=run.run_id, mission_id=run.mission_id,
            graph_version=run.execution_state.get("graphVersion", 1),
            plan_version=run.execution_state.get("taskPlanVersion", workspace_snapshot.get("planVersion", 1)),
            workspace_discovery=workspace_snapshot,
            planning_commit_rejection=run.execution_state.get("planningCommitRejection"))
        material = load_workspace_discovery_materials(store, observation)
        add("workspace_material", "Current sealed workspace evidence and findings",
            workspace_planning_material(material), original_ref=workspace_snapshot["contextRef"],
            trust="host_recorded")
    add("task_plan", "Accepted task plan and graph", {
        "taskPlan": deepcopy(run.execution_state.get("taskPlan")),
        "graph": {**_pick(run.acg_blueprint or {}, ("graphId", "version", "objective", "edges")),
            "nodes": [_pick(node, ("nodeId", "nodeType", "name", "goal", "logicalRole", "capability",
                "acceptanceCriteria", "sourceRefs", "outputSpec")) | {"inputSpec": _pick(node.get("inputSpec"), _STEP_INPUT)}
                for node in (run.acg_blueprint or {}).get("nodes", ())]},
        "steps": [{"stepId": step.step_id, "name": step.name, "goal": step.goal,
            "status": step.status.value, "attempt": step.attempt, "logicalRole": step.logical_role,
            "acceptanceCriteria": list(step.acceptance_criteria), "sourceRefs": list(step.source_refs),
            "input": _pick(step.input, _STEP_INPUT)}
            for step in run.steps]}, trust="accepted_plan")

    list_nodes = getattr(store, "list_node_executions", None)
    nodes = list_nodes(run_id=run.run_id) if callable(list_nodes) else ()
    for node in nodes:
        if node.artifact_refs.get("context"):
            identity = dict(step_id=node.step_id, attempt_id=node.attempt_id, operation_id=node.operation_id,
                original_ref=node.artifact_refs["context"])
            try:
                context = ContextPack.model_validate(store.get_node_input_context(run_id=run.run_id,
                    operation_id=node.operation_id))
            except (ValueError, TypeError, KeyError) as exc:
                unavailable("attempt_input", f"Unavailable input for {node.step_id}", exc, **identity)
            else:
                add("attempt_input", f"Input supplied to {node.step_id}", context.model_dump(by_alias=True, mode="json"),
                    **identity, status=node.phase.value, trust="assembled_context")
        memory = store.get_tool_value(run_id=run.run_id, key=memory_retrieval_key(node.operation_id))
        if memory is not None:
            policy = memory.get("policy") if isinstance(memory, dict) else None
            if isinstance(policy, dict):
                try:
                    admitted = {**policy, "readTypes": [MemoryType(value) for value in policy["readTypes"]],
                        "writeType": MemoryType(policy["writeType"]) if policy.get("writeType") else None}
                    validate_memory_retrieval_snapshot(memory, execution=node, policy=admitted)
                except (ValueError, TypeError, KeyError) as exc:
                    unavailable("memory_retrieval", f"Unavailable recalled memory for {node.step_id}", exc,
                        step_id=node.step_id, attempt_id=node.attempt_id, operation_id=node.operation_id,
                        original_ref=node.artifact_refs.get("memoryInput"))
                else:
                    add("memory_retrieval", f"Frozen recalled memory for {node.step_id}", {
                        "identity": _pick(memory.get("identity"), _IDENTITY),
                        "policy": deepcopy(policy), "records": deepcopy(memory["records"]),
                        "retrievalEvent": deepcopy(memory.get("retrievalEvent"))},
                        step_id=node.step_id, attempt_id=node.attempt_id, operation_id=node.operation_id,
                        original_ref=node.artifact_refs.get("memoryInput"), status=node.phase.value, trust="memory_snapshot")
            else:
                unavailable("memory_retrieval", f"Unavailable recalled memory for {node.step_id}",
                    ValueError("invalid saved memory policy"), step_id=node.step_id, attempt_id=node.attempt_id,
                    operation_id=node.operation_id, original_ref=node.artifact_refs.get("memoryInput"))

    memory_store = getattr(services, "memory_store", None)
    scoped_memories = getattr(memory_store, "values_for_scope", None)
    if callable(scoped_memories):
        now = utc_now()
        for record in scoped_memories(run.run_id):
            if record.scope == run.run_id:
                add("run_memory", f"Run memory {record.memory_id}", {
                    "memory": record.model_dump(by_alias=True, mode="json")}, trust="memory_record",
                    status="expired" if record.expires_at is not None and record.expires_at <= now else "available")

    list_tools = getattr(store, "list_tool_references", None)
    for ref in list_tools(run_id=run.run_id) if callable(list_tools) else ():
        if ref.step_id in {PLANNING_CONTEXT_OWNER, "__planner__", "__planner_catalog__"}:
            continue
        try:
            payload = store.get_output(run_id=run.run_id, output_ref=ref.reference)
            projected = _tool_snapshot(payload, run.run_id, ref.step_id)
        except (ValueError, TypeError, KeyError) as exc:
            unavailable("tool_context", f"Unavailable tool context for {ref.step_id}", exc,
                step_id=ref.step_id, original_ref=ref.reference)
            continue
        if projected is not None:
            kind, status, trust, body = projected
            identity = payload.get("identity") or payload.get("record") or _pick(payload, _IDENTITY)
            add(kind, f"{kind} for {ref.step_id}", body, step_id=ref.step_id,
                attempt_id=identity.get("attemptId"), operation_id=identity.get("commitId"),
                original_ref=ref.reference, status=status, trust=trust)

    raw_loop = run.execution_state.get("planningLoop")
    if isinstance(raw_loop, dict):
        loop = RuntimePlanningState.model_validate(raw_loop)
        current = loop.current
        if current is not None:
            prior = current.observation
            entries.extend(item for item in prior.context_catalog if item.context_kind == "planning_round")
            same_frontier = (prior.graph_version == run.execution_state.get("graphVersion")
                and {fact.step_id: fact.status for fact in prior.steps}
                    == {step.step_id: step.status.value for step in run.steps}
                and {fact.step_id: fact.output_ref for fact in prior.steps if fact.output_ref}
                    == (run.execution_state.get("outputRefs") or {}))
            if not same_frontier:
                # Only an earlier execution frontier becomes history. Keeping
                # the active round out avoids making its own fingerprint drift.
                historical = current.model_dump(by_alias=True, mode="json")
                historical["observation"].pop("contextCatalog", None)
                add("planning_round", "Previous persisted planning boundary", {"planningRound": historical},
                    status=current.status, trust="planning_record")
        if loop.human_answers or loop.user_inputs:
            add("operator_input", "Submitted operator answers and requirements", {
                "humanAnswers": [item.model_dump(by_alias=True, mode="json") for item in loop.human_answers],
                "userInputs": [item.model_dump(by_alias=True, mode="json") for item in loop.user_inputs]},
                trust="caller_supplied")
    for ref in store.list_references(run_id=run.run_id, older_than=utc_now()):
        if ref.kind == "graph-patch":
            add("graph_patch", "Recorded graph patch proposal", {
                "patch": store.get_graph_patch(run_id=run.run_id, patch_ref=ref.reference)},
                original_ref=ref.reference, status="recorded", trust="planning_proposal")
    if run.execution_state.get("failureEvents") or run.execution_state.get("taskSettlement"):
        add("execution_diagnostics", "Execution failure and settlement records", {
            "failureEvents": deepcopy(run.execution_state.get("failureEvents") or []),
            "taskSettlement": deepcopy(run.execution_state.get("taskSettlement") or {})})
    return tuple(entries)


__all__ = ["build_planning_context_catalog"]
