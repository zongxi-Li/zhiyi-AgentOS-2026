"""Reference-first HTTP projection of the single wkn ``WorkflowRuntime``."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.execution.coordinator import RunExecutionCoordinator
from app.security.internal_auth import current_trusted_user
from contracts.workflow import ReviewDecision, ReviewDecisionType, WorkflowRun
from runtime import WorkflowRuntime


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    domain: str = "general"
    intent: str = "general"
    workflow_id: str | None = Field(default=None, alias="workflowId")
    review_mode: str = Field(default="auto", alias="reviewMode")
    input: dict[str, Any] = Field(default_factory=dict)
    security_level: str = Field(default="internal", alias="securityLevel")
    priority: str = "normal"
    enabled_plugin_ids: list[str] | None = Field(default=None, alias="enabledPluginIds")
    client_request_id: str | None = Field(default=None, alias="clientRequestId", max_length=200)


class ReviewApplyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    step_id: str = Field(alias="stepId", min_length=1)
    decision: ReviewDecisionType
    reviewer: str = "system"
    comment: str = Field(default="", max_length=2000)
    operation_id: str = Field(alias="operationId", min_length=1)


class EvolutionRollbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    target_version: int = Field(alias="targetVersion", ge=0)
    reviewer: str = Field(min_length=1)


class EvolutionApprovalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    reviewer: str = Field(min_length=1)


_SENSITIVE_KEYS = (
    "authorization", "password", "secret", "token", "cookie", "api_key",
    "apikey", "prompt", "arguments", "response", "content", "input",
)


def _redact(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if any(marker in str(key).lower().replace("-", "_") for marker in _SENSITIVE_KEYS)
                else _redact(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [_redact(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    return value


def _actor_input(payload: dict[str, Any]) -> dict[str, Any]:
    actor = current_trusted_user()
    if actor is None:
        return dict(payload)
    result = {
        **payload,
        "authenticatedUserId": actor.user_id,
        "authenticatedSubject": actor.subject,
        "authenticatedRole": actor.role,
    }
    if actor.tenant_id:
        result["authenticatedTenantId"] = actor.tenant_id
    return result


def _require_access(run: WorkflowRun) -> None:
    owner = str(run.input.get("authenticatedUserId") or "")
    if not owner:
        return
    actor = current_trusted_user()
    tenant = str(run.input.get("authenticatedTenantId") or "")
    if actor is None or actor.user_id != owner or (tenant and actor.tenant_id != tenant):
        raise HTTPException(status_code=404, detail="run not found")


def _state(run: WorkflowRun) -> dict[str, Any]:
    raw = run.execution_state if isinstance(run.execution_state, dict) else {}
    allowed = (
        "graphId", "graphVersion", "checkpointId", "outputRefs", "contextRefs",
        "memoryRefs", "phaseCapsuleRefs", "traceRefs", "provenanceRefs", "graphPatchRefs",
        "outputSummaries", "resourceBindings", "bindingHistory",
        "bindingRequirements", "executionBindings", "schedulingDecisions",
        "evolutionPolicyVersion",
    )
    return {key: raw[key] for key in allowed if key in raw}


_HISTORY_INPUT_KEYS = (
    "taskName", "taskGoal", "userIntent", "materialText", "materialIds", "constraints",
    "expectedArtifacts", "planningMode", "planningDiversity", "planningSeed", "webSearchEnabled",
    "thinkingMode", "pluginData", "contractText", "contractType", "legalReviewGoal",
    "evidenceFirst", "riskParallel", "conservativeReview",
)


def _history_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [_history_value(item) for item in value[:100] if isinstance(item, (str, int, float, bool, dict, list))]
    if isinstance(value, dict):
        return {
            str(key): _history_value(item)
            for key, item in list(value.items())[:100]
            if not any(marker in str(key).lower().replace("-", "_") for marker in _SENSITIVE_KEYS)
        }
    return None


def project_history_config(run: WorkflowRun, *, title: str | None = None) -> dict[str, Any]:
    """Return only the owner-visible configuration needed to reopen a historical workbench."""
    raw = run.input if isinstance(run.input, dict) else {}
    return {
        "runId": run.run_id,
        "title": title or str(raw.get("taskName") or ""),
        "reviewMode": run.review_mode,
        "enabledPluginIds": list(run.enabled_plugin_ids),
        "input": {
            key: _history_value(raw[key])
            for key in _HISTORY_INPUT_KEYS
            if key in raw
        },
    }


def _legacy_provenance_items(value: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {key: _redact(item[key]) for key in allowed if key in item}
        for item in value[:100]
        if isinstance(item, dict)
    ]


def project_run(run: WorkflowRun, *, title: str | None = None) -> dict[str, Any]:
    """Project lifecycle and references without task input or output bodies."""
    state = _state(run)
    return {
        "runId": run.run_id,
        "taskId": run.task_id,
        "title": title,
        "workflowId": run.workflow_id,
        "domain": run.domain,
        "runtimeEngine": run.runtime_engine,
        "status": run.status.value,
        "lifecyclePhase": run.lifecycle_phase.value if run.lifecycle_phase else None,
        "lifecycleMessage": run.lifecycle_message,
        "currentStepId": run.current_step_id,
        "completedStepIds": list(run.completed_step_ids),
        "activeStepIds": list(run.active_step_ids),
        "skippedStepIds": list(run.execution_state.get("skippedStepIds") or []),
        "outputRef": run.output.get("outputRef") if isinstance(run.output, dict) else None,
        "executionState": state,
        "steps": [
            {
                "stepId": step.step_id,
                "name": step.name,
                "agentName": step.agent_name,
                "capability": step.capability,
                "status": step.status.value,
                "attempt": step.attempt,
                "retryCount": step.retry_count,
                "reviewRequired": step.requires_review,
                "outputRef": (state.get("outputRefs") or {}).get(step.step_id),
                "outputSummary": (state.get("outputSummaries") or {}).get(step.step_id, ""),
                "startedAt": step.started_at,
                "completedAt": step.completed_at,
            }
            for step in run.steps
        ],
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
        "startedAt": run.started_at,
    }


def project_graph(run: WorkflowRun) -> dict[str, Any]:
    blueprint = dict(run.acg_blueprint or {})
    state = _state(run)
    return {
        "runId": run.run_id,
        "graphId": blueprint.get("graphId") or state.get("graphId"),
        "graphVersion": blueprint.get("version") or state.get("graphVersion"),
        "nodes": list(blueprint.get("nodes") or []),
        "edges": list(blueprint.get("edges") or []),
        "completedStepIds": list(run.completed_step_ids),
        "activeStepIds": list(run.active_step_ids),
        "skippedStepIds": list(run.execution_state.get("skippedStepIds") or []),
        "graphPatchRefs": list(state.get("graphPatchRefs") or []),
        "resourceBindings": dict(state.get("resourceBindings") or {}),
    }


def _idempotency(request: RunCreateRequest) -> tuple[str | None, str | None]:
    if not request.client_request_id:
        return None, None
    actor = current_trusted_user()
    caller = f"{getattr(actor, 'tenant_id', '')}:{getattr(actor, 'user_id', '')}" if actor else "internal"
    key = hashlib.sha256(f"{caller}:agentos-v2:{request.client_request_id}".encode()).hexdigest()
    body = request.model_dump(by_alias=True, mode="json", exclude={"client_request_id"})
    fingerprint = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return key, fingerprint


def create_router(runtime: WorkflowRuntime, coordinator: RunExecutionCoordinator) -> APIRouter:
    router = APIRouter(prefix="/agentos/v2")

    def load_run(run_id: str) -> WorkflowRun:
        try:
            run = runtime.get_status(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        _require_access(run)
        return run

    def project(run: WorkflowRun) -> dict[str, Any]:
        try:
            title = runtime.workflow_store.get_task(run.task_id).title
        except KeyError:
            title = None
        return project_run(run, title=title)

    @router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
    async def create_run(request: RunCreateRequest):
        key, fingerprint = _idempotency(request)
        if key:
            existing = runtime.workflow_store.find_run_by_idempotency_key(key)
            if existing is not None:
                _require_access(existing)
                if existing.idempotency_fingerprint != fingerprint:
                    raise HTTPException(status_code=409, detail="clientRequestId conflict")
                return project(existing)
        try:
            task = runtime.create_task(
                title=request.title,
                domain=request.domain,
                intent=request.intent,
                input=_actor_input(request.input),
                security_level=request.security_level,
                priority=request.priority,
                workflow_id=request.workflow_id,
                enabled_plugin_ids=request.enabled_plugin_ids,
            )
            _, run = runtime.prepare_run(
                task.task_id,
                workflow_id=request.workflow_id,
                review_mode=request.review_mode,
                idempotency_key=key,
                idempotency_fingerprint=fingerprint,
                enabled_plugin_ids=request.enabled_plugin_ids,
            )
            await coordinator.submit(run.run_id)
            return project(runtime.get_status(run.run_id))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="invalid workflow request") from exc

    @router.get("/runs")
    async def list_runs(
        status_value: str | None = Query(default=None, alias="status"),
        domain: str | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    ):
        actor = current_trusted_user()
        result = runtime.workflow_store.list_runs(
            status=status_value,
            domain=domain,
            owner_user_id=(actor.user_id if actor else None),
            owner_tenant_id=(actor.tenant_id if actor else None),
            page=page,
            page_size=page_size,
        )
        return {
            "items": [project(run) for run in result.items],
            "total": result.total,
            "page": result.page,
            "pageSize": result.page_size,
        }

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        return project(load_run(run_id))

    @router.get("/runs/{run_id}/history-config")
    async def get_history_config(run_id: str):
        run = load_run(run_id)
        try:
            title = runtime.workflow_store.get_task(run.task_id).title
        except KeyError:
            title = None
        return project_history_config(run, title=title)

    @router.get("/runs/{run_id}/graph")
    async def get_graph(run_id: str):
        return project_graph(load_run(run_id))

    @router.get("/runs/{run_id}/outputs/{output_ref}")
    async def get_output(run_id: str, output_ref: str):
        run = load_run(run_id)
        allowed = set((_state(run).get("outputRefs") or {}).values())
        if output_ref not in allowed:
            raise HTTPException(status_code=404, detail="output not found")
        try:
            content = runtime.execution_value_store.get_output(run_id=run_id, output_ref=output_ref)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="output not found") from exc
        return {"runId": run_id, "outputRef": output_ref, "content": content}

    @router.get("/runs/{run_id}/legacy-outputs")
    async def get_legacy_outputs(run_id: str):
        run = load_run(run_id)
        if _state(run).get("outputRefs"):
            raise HTTPException(status_code=404, detail="legacy outputs not found")
        items = [
            {
                "stepId": step.step_id,
                "name": step.name,
                "status": step.status.value,
                "content": dict(step.output),
            }
            for step in run.steps
            if isinstance(step.output, dict) and step.output
        ]
        if not items:
            raise HTTPException(status_code=404, detail="legacy outputs not found")
        return {"runId": run_id, "items": items}

    @router.get("/runs/{run_id}/trace")
    async def get_trace(run_id: str):
        run = load_run(run_id)
        exported = runtime.trace_store.export_json(run)
        exported["events"] = [_redact(item) for item in exported.get("events", [])]
        return exported

    @router.get("/runs/{run_id}/provenance")
    async def get_provenance(run_id: str):
        run = load_run(run_id)
        ledger = runtime.provenance_store.load_ledger(run_id=run.run_id, task_id=run.task_id)
        events = ledger.trace_events()
        legacy = run.provenance if isinstance(run.provenance, dict) else {}
        if not events and any(isinstance(legacy.get(key), list) and legacy[key] for key in ("productions", "consumptions", "interactions")):
            common = {"eventId", "runId", "taskId", "attempt", "previousHash", "eventHash", "createdAt"}
            return {
                "runId": run.run_id,
                "schemaVersion": legacy.get("schemaVersion"),
                "integrityStatus": legacy.get("integrityStatus", "unknown"),
                "productions": _legacy_provenance_items(legacy.get("productions"), common | {
                    "producerStepId", "agentName", "checksum", "fieldNames", "tokenSize", "evidenceRefs",
                }),
                "consumptions": _legacy_provenance_items(legacy.get("consumptions"), common | {
                    "consumerStepId", "producerStepIds", "consumerAgentName", "producerEventIds",
                    "consumedFields", "fieldsByProducer", "tokensDelivered", "tokensAvailable",
                    "savingRatio", "contractStatus", "checksum",
                }),
                "interactions": _legacy_provenance_items(legacy.get("interactions"), common | {
                    "interactionId", "edgeIds", "producerStepIds", "consumerStepId",
                    "producerAgentNames", "consumerAgentName", "fieldsByProducer", "tokensDelivered",
                    "tokensAvailable", "savingRatio", "evidenceRefs", "contractStatus", "checksum",
                }),
                "legacy": True,
            }
        return {
            "runId": run.run_id,
            "integrityStatus": "valid" if ledger.verify_integrity() else "invalid",
            "events": events,
        }

    @router.get("/runs/{run_id}/checkpoints")
    async def get_checkpoints(run_id: str):
        run = load_run(run_id)
        checkpoint_id = str(run.execution_state.get("checkpointId") or "")
        items = []
        if checkpoint_id:
            items.append(
                {
                    "checkpointId": checkpoint_id,
                    "version": runtime.checkpoint_store.version(run_id=run_id, checkpoint_id=checkpoint_id),
                    "canResume": run.status.value == "waiting_review",
                }
            )
        return {"runId": run_id, "items": items, "total": len(items)}

    @router.get("/runs/{run_id}/reviews")
    async def get_reviews(run_id: str):
        load_run(run_id)
        reviews = runtime.list_reviews(run_id)
        return {
            "runId": run_id,
            "items": [item.model_dump(by_alias=True, mode="json") for item in reviews],
            "total": len(reviews),
        }

    @router.get("/runs/{run_id}/scheduling")
    async def get_scheduling(run_id: str):
        run = load_run(run_id)
        items = list(run.execution_state.get("schedulingDecisions") or [])
        return {"runId": run_id, "items": _redact(items), "total": len(items)}

    @router.get("/runs/{run_id}/memory-events")
    async def get_memory_events(run_id: str):
        run = load_run(run_id)
        items = []
        for event in run.trace:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if "retrievalMode" in payload:
                items.append({
                    "kind": "memory_access",
                    "stepId": event.step_id,
                    "retrievalMode": payload.get("retrievalMode"),
                    "hitRefs": list(payload.get("hitRefs") or []),
                    "budget": payload.get("tokenBudget"),
                    "fallbackReason": payload.get("fallbackReason"),
                    "createdAt": event.created_at,
                })
            elif event.observation == "Structured memory event projected":
                items.append({"kind": "memory_event", **_redact(payload)})
            elif payload.get("kind") == "phase_capsule":
                items.append({"kind": "phase_capsule", **_redact(payload)})
        return {"runId": run_id, "items": items, "total": len(items)}

    @router.get("/evolution/active")
    async def get_active_evolution_policy():
        return runtime.evolution_service.store.active().model_dump(by_alias=True, mode="json")

    @router.get("/evolution/history")
    async def get_evolution_history():
        items = [
            item.model_dump(by_alias=True, mode="json")
            for item in runtime.evolution_service.store.list_versions()
        ]
        return {"items": items, "total": len(items)}

    @router.post("/runs/{run_id}/evolution-proposals")
    async def create_evolution_proposal(run_id: str):
        load_run(run_id)
        try:
            trajectory, evaluation, proposal = runtime.propose_evolution_from_run(run_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="evolution proposal conflict") from exc
        return {
            "trajectory": trajectory.model_dump(by_alias=True, mode="json"),
            "evaluation": evaluation.model_dump(by_alias=True, mode="json"),
            "proposal": proposal.model_dump(by_alias=True, mode="json"),
        }

    @router.post("/evolution/proposals/{proposal_id}/approve")
    async def approve_evolution_proposal(
        proposal_id: str, request: EvolutionApprovalRequest
    ):
        try:
            version = runtime.approve_evolution_proposal(
                proposal_id,
                approved_by=request.reviewer,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="evolution approval conflict") from exc
        return version.model_dump(by_alias=True, mode="json")

    @router.post("/evolution/rollback")
    async def rollback_evolution_policy(request: EvolutionRollbackRequest):
        try:
            version = runtime.evolution_service.rollback(
                request.target_version, approved_by=request.reviewer
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="evolution rollback conflict") from exc
        return version.model_dump(by_alias=True, mode="json")

    @router.post("/runs/{run_id}/reviews")
    async def apply_review(run_id: str, request: ReviewApplyRequest):
        load_run(run_id)
        try:
            run = await runtime.apply_review(
                ReviewDecision(
                    runId=run_id,
                    stepId=request.step_id,
                    decision=request.decision,
                    reviewer=request.reviewer,
                    comment=request.comment,
                    operationId=request.operation_id,
                )
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="review conflict") from exc
        return project(run)

    return router


__all__ = ["EvolutionApprovalRequest", "EvolutionRollbackRequest", "RunCreateRequest", "ReviewApplyRequest", "create_router", "project_graph", "project_run"]
