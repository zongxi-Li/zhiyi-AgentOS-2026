"""Controlled policy evolution derived from completed General trajectories."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts import stable_checksum
from contracts.evolution import (
    EvolutionPolicyVersion,
    EvolutionProposal,
    EvolutionProposalStatus,
    PolicyMutation,
    Trajectory,
    TrajectoryEvaluation,
    TrajectoryStep,
)
from contracts.workflow import RuntimeRunRecord

from .store import EvolutionStore, InMemoryEvolutionStore


class EvolutionService:
    def __init__(self, *, store: EvolutionStore | None = None, proposal_threshold: int = 3) -> None:
        if proposal_threshold < 1:
            raise ValueError("proposal_threshold must be positive")
        self.store = store or InMemoryEvolutionStore()
        self.proposal_threshold = proposal_threshold

    def evaluate(self, trajectory: Trajectory) -> TrajectoryEvaluation:
        completed = str(trajectory.outcome.get("status", "")).lower() in {"completed", "success"}
        success = 1.0 if completed or trajectory.outcome.get("success") is True else 0.0
        step_count = max(len(trajectory.steps), 1)
        failed_steps = sum(bool(step.feedback.get("error")) for step in trajectory.steps)
        efficiency = max(0.0, 1.0 - failed_steps / step_count)
        quality = min(1.0, float(trajectory.outcome.get("quality", success)))
        evaluation = TrajectoryEvaluation(
            trajectoryId=trajectory.trajectory_id,
            successScore=success,
            efficiencyScore=efficiency,
            noveltyScore=0.0,
            qualityScore=quality,
            evidence={"stepCount": len(trajectory.steps), "failedSteps": failed_steps},
        )
        self.store.save_evaluation(evaluation)
        return evaluation

    def project_run(
        self,
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
        return self.store.save_trajectory(trajectory)

    def propose(
        self,
        trajectories: list[Trajectory],
        mutation: PolicyMutation,
    ) -> EvolutionProposal | None:
        ordered = sorted(trajectories, key=lambda item: item.trajectory_id)
        if len(ordered) < self.proposal_threshold:
            return None
        evaluations = [self.evaluate(item) for item in ordered]
        checksum = stable_checksum(evaluations)
        active = self.store.active()
        proposal_id = f"evolution:{stable_checksum([active.version, [item.trajectory_id for item in ordered], mutation])[:16]}"
        proposal = EvolutionProposal(
            proposalId=proposal_id,
            baseVersion=active.version,
            trajectoryIds=[item.trajectory_id for item in ordered],
            mutations=[mutation],
            evaluationChecksum=checksum,
            status=EvolutionProposalStatus.PENDING_REVIEW,
        )
        self.validate_proposal(proposal)
        return self.store.save_proposal(proposal)

    def propose_from_run(
        self,
        run: RuntimeRunRecord,
        *,
        provenance_events: list[dict],
    ) -> tuple[Trajectory, TrajectoryEvaluation, EvolutionProposal]:
        trajectory = self.project_run(run, provenance_events=provenance_events)
        evaluation = self.evaluate(trajectory)
        proposal = self.propose(
            [trajectory],
            PolicyMutation(
                mutationType="budget_adjustment",
                target="memory_token_budget",
                value=768,
            ),
        )
        if proposal is None:
            raise ValueError("real-run trajectory threshold was not met")
        return trajectory, evaluation, proposal

    def validate_proposal(self, proposal: EvolutionProposal) -> None:
        if proposal.base_version != self.store.active().version:
            raise ValueError("proposal base version is stale")
        evaluations = [self.store.get_evaluation(item) for item in proposal.trajectory_ids]
        if stable_checksum(evaluations) != proposal.evaluation_checksum:
            raise ValueError("proposal evaluation checksum is invalid")
        for mutation in proposal.mutations:
            if mutation.mutation_type == "budget_adjustment":
                if (
                    not isinstance(mutation.value, (int, float))
                    or isinstance(mutation.value, bool)
                    or mutation.value <= 0
                ):
                    raise ValueError("budget adjustment must be a positive number")

    def approve(self, proposal: EvolutionProposal, *, approved_by: str) -> EvolutionPolicyVersion:
        if proposal.status is not EvolutionProposalStatus.PENDING_REVIEW:
            raise ValueError("only a validated pending proposal can be approved")
        active = self.store.active()
        if proposal.base_version != active.version:
            raise ValueError("proposal base version is stale")
        persisted = self.store.get_proposal(proposal.proposal_id)
        if persisted != proposal:
            raise ValueError("proposal does not match the validated persisted proposal")
        self.validate_proposal(proposal)
        policy = dict(active.policy)
        for mutation in proposal.mutations:
            policy[f"{mutation.mutation_type}:{mutation.target}"] = mutation.value
        version = self.store.create(
            EvolutionPolicyVersion(
                version=active.version + 1,
                baseVersion=active.version,
                proposalIds=[proposal.proposal_id],
                policy=policy,
                approvedBy=approved_by,
            ),
            expected_active=active.version,
        )
        self.store.save_proposal(proposal.model_copy(update={
            "status": EvolutionProposalStatus.APPROVED,
            "reviewed_by": approved_by,
            "reviewed_at": datetime.now(timezone.utc),
        }))
        return version

    def rollback(self, target_version: int, *, approved_by: str) -> EvolutionPolicyVersion:
        target = self.store.get(target_version)
        active = self.store.active()
        return self.store.create(
            EvolutionPolicyVersion(
                version=active.version + 1,
                baseVersion=active.version,
                proposalIds=[f"rollback:{target_version}"],
                policy=dict(target.policy),
                approvedBy=approved_by,
            ),
            expected_active=active.version,
        )


__all__ = ["EvolutionService"]
