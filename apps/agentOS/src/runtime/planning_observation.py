"""Build a current planning observation from existing durable runtime authorities."""

from components.auditor.artifact_acceptance import OBSERVATION_EXCERPT_BYTES, inspect_artifact
from components.auditor.task_acceptance import evaluate_task_acceptance
from contracts.planning import TaskPlan, TaskImplementationBinding
from contracts.runtime_planning import RuntimePlanningObservation, RuntimePlanningState, StepObservation
from contracts.workflow import StepStatus, TraceEventType
from contracts.task_acceptance import frozen_task_acceptance
from runtime.ports import CollaboratorAccess


class RuntimePlanningObservationBuilder(CollaboratorAccess):
    def __init__(self, *, collaborators, load_goal, validate_references):
        self.ports = collaborators
        self.load_goal = load_goal
        self.validate_references = validate_references

    def _committed(self, run_id: str, step_id: str, output_ref: str, visited: frozenset[str] = frozenset()):
        """Follow the existing retry's copied-reference lineage back to its audit."""
        if run_id in visited:
            raise ValueError("cyclic reused output lineage")
        self.execution_value_store.assert_reference(kind="output", run_id=run_id, step_id=step_id, reference=output_ref)
        commits = [c for c in self.execution_value_store.list_node_commits(run_id=run_id)
            if c.get("stage") == "committed" and c.get("outputRef") == output_ref]
        if len(commits) != 1:
            raise ValueError("completed output requires one immutable node commit")
        commit = commits[0]
        source_id, source_ref = commit.get("reusedFromRunId"), commit.get("reusedFromOutputRef")
        if source_id and source_ref:
            return self._committed(source_id, step_id, source_ref, visited | {run_id})
        decision_ref = commit.get("auditDecisionRef")
        if not isinstance(decision_ref, str):
            raise ValueError("completed node requires a persisted audit decision")
        decision = self.decision_store.assert_decision(run_id=run_id, step_id=step_id, decision_ref=decision_ref, outcomes={"allow", "review"})
        return commit, decision, run_id

    def observe(self, run, state, reason) -> RuntimePlanningObservation:
        self.validate_references(run=run, state=state)
        acceptance = frozen_task_acceptance(run)
        plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
        bindings = [TaskImplementationBinding.model_validate(b) for b in run.execution_state["taskBindings"]]
        task_by_step = {b.acg_node_id: b.plan_node_key for b in bindings}
        blockers, facts = [], []
        acceptance_candidates = []
        excerpt_budget = OBSERVATION_EXCERPT_BYTES
        for step in run.steps:
            output_ref = state.output_refs.get(step.step_id)
            data = dict(stepId=step.step_id, taskKey=task_by_step[step.step_id], status=step.status.value)
            if step.step_id in state.completed_step_ids:
                if not output_ref:
                    raise ValueError("completed step has no durable output")
                commit, audit, owner_id = self._committed(run.run_id, step.step_id, output_ref)
                review_resolved = True
                if audit.outcome == "review" or step.requires_review:
                    owner = self.workflow_store.get_run(owner_id)
                    approved = any(e.event_type == TraceEventType.REVIEW_DECIDED and e.step_id == step.step_id and e.payload.get("decision") == "approved" for e in owner.trace)
                    if not approved:
                        review_resolved = False
                        blockers.append(f"review_unresolved:{step.step_id}")
                payload = self.execution_value_store.get_output(run_id=run.run_id, output_ref=output_ref)
                verification = payload.get("verification") if step.capability == "verification" else None
                report = verification.get("status") if isinstance(verification, dict) else None
                if report not in {None, "passed", "partial", "failed"}:
                    raise ValueError("unknown persisted verification status")
                if report in {"partial", "failed"}:
                    blockers.append(f"verification_{report}:{step.step_id}")
                artifacts, evidence = [], []
                for artifact in commit.get("artifacts") or []:
                    manifest_id = artifact.get("manifestId")
                    if not manifest_id:
                        blockers.append(f"artifact_unsealed:{step.step_id}")
                        continue
                    inspected, used = inspect_artifact(
                        store=self.content_manifest_store, artifact=artifact, owner_id=owner_id,
                        commit_id=commit["commitId"], excerpt_budget=excerpt_budget,
                        review_resolved=review_resolved,
                    )
                    excerpt_budget -= used
                    evidence.append(inspected)
                    acceptance_candidates.append({"artifactKey": artifact.get("artifactKey", "primary"),
                        "taskKey": data["taskKey"], "evidence": inspected, "reviewResolved": review_resolved})
                    blockers.extend(f"artifact_{check.check}:{manifest_id}"
                        for check in inspected.checks if check.outcome == "failed")
                    artifacts.append(manifest_id)
                semantic = next(t for t in plan.nodes if t.key == data["taskKey"])
                if semantic.produced_artifacts and not artifacts:
                    blockers.append(f"artifact_missing:{step.step_id}")
                data.update(outputRef=output_ref, commitId=commit["commitId"], auditRef=audit.decision_id,
                    auditOutcome=audit.outcome, verificationReport=report, artifactRefs=tuple(artifacts),
                    artifactEvidence=tuple(evidence))
            facts.append(StepObservation(**data))
        settled = set(state.completed_step_ids) | set(state.skipped_step_ids)
        remaining = tuple(s.step_id for s in run.steps if s.step_id not in settled)
        acceptance_results = evaluate_task_acceptance(store=self.content_manifest_store,
            spec=acceptance, candidates=acceptance_candidates) if acceptance else ()
        if not remaining:
            blockers.extend(f"task_acceptance_{r.outcome}:{r.criterion_id}"
                for r in acceptance_results if r.outcome != "passed")
        if not remaining and plan.expected_artifacts:
            delivered = {
                artifact for task in plan.nodes
                if any(f.task_key == task.key and f.artifact_refs for f in facts)
                for artifact in task.produced_artifacts
            }
            blockers.extend(f"expected_artifact_missing:{a}" for a in plan.expected_artifacts if a not in delivered)
        failures = run.execution_state.get("failureEvents") or []
        failure = failures[-1] if reason in {"failure", "condition", "user_input"} and failures else {}
        resources = tuple(
            (p.node_id, self.resource_plane.node_health(p.node_id).status.value)
            for p in self.resource_plane.nodes()
        )
        planning = RuntimePlanningState.model_validate(run.execution_state.get("planningLoop") or {})
        return RuntimePlanningObservation(
            missionId=run.mission_id, runId=run.run_id, graphId=state.graph_id,
            graphVersion=state.graph_version, planVersion=plan.plan_version,
            checkpointId=state.checkpoint_id, wakeReason=reason, goal=self.load_goal(run.mission_id),
            steps=tuple(facts), remainingStepIds=remaining,
            failureId=failure.get("failureId"), failureType=failure.get("failureType"),
            recoveryAction=(run.execution_state.get("recoveryOutcome") or {}).get("action") if failure else None,
            failedStepIds=tuple(s.step_id for s in run.steps if s.status == StepStatus.FAILED),
            completionBlockers=tuple(blockers), resources=resources,
            taskAcceptance=acceptance, taskAcceptanceResults=acceptance_results,
            conditionWake=planning.waiting.wake if reason == "condition" and planning.waiting else None,
            humanAnswers=planning.human_answers,
            userInputs=planning.user_inputs,
        )
