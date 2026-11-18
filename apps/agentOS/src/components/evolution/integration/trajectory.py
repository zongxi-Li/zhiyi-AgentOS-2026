"""Deterministic, reference-only adaptation of persisted AgentOS execution records."""
from contracts import stable_checksum
from contracts.evolution import Trajectory, TrajectoryStep
from contracts.workflow import RuntimeRunRecord


def project_run(
    run: RuntimeRunRecord,
    *,
    provenance_events: list[dict],
) -> Trajectory:
    """Project one persisted run using references and audit metadata only."""
    scheduling = {
        str(item.get("stepId")): item
        for item in run.execution_state.get("schedulingDecisions") or []
        if isinstance(item, dict) and item.get("stepId")
    }
    memory_events = {
        str(event.payload.get("stepId") or event.step_id): dict(event.payload)
        for event in run.trace
        if event.observation == "Structured memory event projected"
    }
    review_by_step = {
        str(event.step_id): str(event.payload.get("decision") or "")
        for event in run.trace
        if event.event_type.value == "review_decided" and event.step_id
    }
    memory_hits_by_step = {
        str(event.step_id): list(event.payload.get("hitRefs") or [])
        for event in run.trace
        if event.step_id and "retrievalMode" in event.payload
    }
    provenance_by_step: dict[str, list[str]] = {}
    for event in provenance_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            event = payload
        step_id = str(
            event.get("producerStepId")
            or event.get("consumerStepId")
            or ""
        )
        event_id = event.get("eventId")
        if step_id and isinstance(event_id, str):
            provenance_by_step.setdefault(step_id, []).append(event_id)
    steps: list[TrajectoryStep] = []
    for step in run.steps:
        decision = scheduling.get(step.step_id) or {}
        binding = decision.get("binding") if isinstance(decision.get("binding"), dict) else {}
        lease = decision.get("lease") if isinstance(decision.get("lease"), dict) else {}
        memory_event = memory_events.get(step.step_id) or {}
        steps.append(TrajectoryStep(
            stepId=step.step_id,
            actionType=step.capability or step.agent_name,
            input={
                "candidateCount": len(decision.get("candidates") or []),
                "bindingRef": binding.get("resourceId"),
                "leaseRef": lease.get("leaseId"),
                "leaseStatus": lease.get("status"),
                "memoryEventRef": memory_event.get("eventId"),
                "memoryHitRefs": memory_hits_by_step.get(step.step_id, []),
            },
            output={
                "outputRef": (run.execution_state.get("outputRefs") or {}).get(step.step_id),
                "outputSummary": (run.execution_state.get("outputSummaries") or {}).get(step.step_id),
                "provenanceRefs": sorted(provenance_by_step.get(step.step_id, [])),
                "evidenceRefs": list(memory_event.get("evidenceRefs") or []),
            },
            feedback={
                "status": step.status.value,
                "memoryDecision": memory_event.get("decision"),
                "reviewDecision": review_by_step.get(step.step_id),
                "error": bool(step.error),
            },
        ))
    projection = {
        "task": {
            "runId": run.run_id,
            "workflowId": run.workflow_id,
            "domain": run.domain,
            "policyVersion": run.execution_state.get("evolutionPolicyVersion"),
            "graphId": run.execution_state.get("graphId"),
        },
        "steps": [step.model_dump(by_alias=True, mode="json") for step in steps],
        "outcome": {
            "status": run.status.value,
            "success": run.status.value == "completed",
            "quality": 1.0 if run.status.value == "completed" else 0.0,
            "checkpointId": run.execution_state.get("checkpointId"),
            "completedStepCount": len(run.completed_step_ids),
            "phaseCapsuleRefs": dict(run.execution_state.get("phaseCapsuleRefs") or {}),
            "traceRefs": [event.event_id for event in run.trace],
        },
        "graphVersion": run.execution_state.get("graphVersion"),
    }
    trajectory = Trajectory(
        trajectoryId=f"trajectory:{run.run_id}:{stable_checksum(projection)[:16]}",
        task=projection["task"],
        steps=steps,
        outcome=projection["outcome"],
        graphVersion=projection["graphVersion"],
    )
    return trajectory

