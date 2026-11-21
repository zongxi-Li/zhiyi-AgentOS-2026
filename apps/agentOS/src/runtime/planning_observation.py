"""Build a current planning observation from existing durable runtime authorities."""

from components.auditor.artifact_acceptance import OBSERVATION_EXCERPT_BYTES, inspect_artifact
from components.auditor.task_acceptance import evaluate_task_acceptance
from contracts.planning import TaskPlan, TaskImplementationBinding
from contracts.runtime_planning import (RuntimePlanningObservation, RuntimePlanningState, StepObservation,
    RuntimeResourceObservation, RuntimeResourceCandidate, RuntimeResourceFailover, requirement_fingerprint)
from contracts.workflow import StepStatus, TraceEventType
from contracts.task_acceptance import frozen_task_acceptance
from runtime.ports import CollaboratorAccess
from contracts.mission_semantic import run_intent_basis
from contracts.artifacts import is_final_synthesis_role
from runtime.binding import assess_run_requirement, effective_recovery_requirement


class RuntimePlanningObservationBuilder(CollaboratorAccess):
    def __init__(self, *, collaborators, load_goal, validate_references):
        self.ports = collaborators
        self.load_goal = load_goal
        self.validate_references = validate_references

    def _committed(self, run_id: str, step_id: str, output_ref: str, visited: frozenset[str] = frozenset()):
        """Follow the existing retry's copied-reference lineage back to its audit."""
        from runtime.planning_results import resolve_committed_result
        return resolve_committed_result(self, run_id, step_id, output_ref, visited)

    def observe(self, run, state, reason) -> RuntimePlanningObservation:
        basis = run_intent_basis(run)
        self.validate_references(run=run, state=state)
        acceptance = frozen_task_acceptance(run)
        raw_plan = run.execution_state.get("taskPlan")
        plan = TaskPlan.model_validate(raw_plan) if raw_plan is not None else None
        bindings = [TaskImplementationBinding.model_validate(b) for b in run.execution_state["taskBindings"]] if plan else ()
        # Legacy executable graphs still need the same deterministic completion
        # checks. Observing their real step identities does not invent a plan.
        task_by_step = ({b.acg_node_id: b.plan_node_key for b in bindings}
                        if plan else {step.step_id: step.step_id for step in run.steps})
        blockers, facts, result_index = [], [], []
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
                semantic = next(t for t in plan.nodes if t.key == data["taskKey"]) if plan else None
                if ((semantic is not None and semantic.produced_artifacts)
                        or is_final_synthesis_role(step.logical_role)) and not artifacts:
                    blockers.append(f"artifact_missing:{step.step_id}")
                tool_outcomes = []
                for call in (commit.get("toolCalls") or ())[:64]:
                    if not isinstance(call, dict):
                        continue
                    tool = call.get("tool") or call.get("name")
                    if not isinstance(tool, str) or not tool:
                        continue
                    status, error, receipt = call.get("status"), call.get("errorCode"), call.get("receiptRef")
                    tool_outcomes.append({"tool": tool[:128],
                        "status": status[:64] if isinstance(status, str) else "unknown",
                        "errorCode": error[:128] if isinstance(error, str) else None,
                        "receiptRef": receipt if isinstance(receipt, str) and len(receipt) <= 256 else None})
                data.update(outputRef=output_ref, commitId=commit["commitId"], auditRef=audit.decision_id,
                    auditOutcome=audit.outcome, verificationReport=report, artifactRefs=tuple(artifacts),
                    artifactEvidence=tuple(evidence), toolOutcomes=tuple(tool_outcomes))
                from runtime.planning_results import committed_result_index_entry
                result_index.append(committed_result_index_entry(step=step, task_key=data["taskKey"], task=semantic,
                    output_ref=output_ref, payload=payload, commit=commit, audit=audit, source_run_id=owner_id,
                    review_resolved=review_resolved, artifact_refs=artifacts))
            facts.append(StepObservation(**data))
        settled = set(state.completed_step_ids) | set(state.skipped_step_ids)
        remaining = tuple(s.step_id for s in run.steps if s.step_id not in settled)
        blockers.extend(self._verification_blockers(run, facts, exhausted=not remaining))
        acceptance_results = evaluate_task_acceptance(store=self.content_manifest_store,
            spec=acceptance, candidates=acceptance_candidates) if acceptance else ()
        from contracts.execution_evidence import (evaluate_run_workspace_observations,
                                                  workspace_observation_progress)
        workspace_progress = workspace_observation_progress(run, self.execution_value_store)
        from runtime.workspace_planning_context import workspace_discovery_snapshot
        discovery = workspace_discovery_snapshot(run, self.execution_value_store)
        if discovery is not None and discovery["phase"] == "discovery" and not remaining:
            blockers.append("workspace_discovery_planning_pending")
        if not remaining:
            blockers.extend(f"task_acceptance_{r.outcome}:{r.criterion_id}"
                for r in acceptance_results if r.outcome != "passed")
            blockers.extend(evaluate_run_workspace_observations(run, self.execution_value_store))
        if not remaining and plan is not None and plan.expected_artifacts:
            delivered = {
                artifact for task in plan.nodes
                if any(f.task_key == task.key and f.artifact_refs for f in facts)
                for artifact in task.produced_artifacts
            }
            blockers.extend(f"expected_artifact_missing:{a}" for a in plan.expected_artifacts if a not in delivered)
        failures = run.execution_state.get("failureEvents") or []
        failure = failures[-1] if reason in {"failure", "condition", "user_input"} and failures else {}
        failed_steps = tuple(s.step_id for s in run.steps if s.status == StepStatus.FAILED)
        recovery_action = (run.execution_state.get("recoveryOutcome") or {}).get("action") if failure else None
        readonly_recovery_proof = None
        if (failure and len(failed_steps) == 1 and recovery_action not in {"retry", "rebind"}
                and failure.get("failureType") not in {"policy", "storage"}):
            from runtime.permit_recovery import run_step_readonly_retry_proof
            try:
                readonly_recovery_proof = run_step_readonly_retry_proof(self, run, failed_steps[0])
            except ValueError:
                # Failed proof preserves the existing Recovery classification.
                # Error text or an Agent's own claim is never a grant.
                pass
            else:
                recovery_action = "retry"
        planning = RuntimePlanningState.model_validate(run.execution_state.get("planningLoop") or {})
        requirements = run.execution_state.get("bindingRequirements") or {}
        # Prefer failed steps; cap the observation rather than exporting the registry.
        targets = sorted(remaining, key=lambda step_id: (run.get_step(step_id).status != StepStatus.FAILED,
            remaining.index(step_id)))[:16]
        resource_facts = []
        for step_id in targets:
            if step_id not in requirements:
                continue
            requirement = effective_recovery_requirement(run, step_id)
            readiness = assess_run_requirement(self, run, requirement)
            candidates = readiness.candidates[:16]
            nodes = {self.resource_plane.runtime(c.resource_id).node_id for c in candidates}
            resource_facts.append(RuntimeResourceObservation(
                stepId=step_id, requirementId=requirement_fingerprint(requirement),
                requiredCapabilities=tuple(requirement.required_capabilities),
                runtimeKinds=tuple(k.value for k in requirement.runtime_kinds),
                allowedPlacements=tuple(p.value for p in requirement.allowed_placements),
                minTrust=requirement.min_trust.value if requirement.min_trust else None,
                domain=requirement.domain, maxCost=requirement.max_cost,
                maxLatencyMs=requirement.max_latency_ms, allowRemoteExecution=requirement.allow_remote_execution,
                modelDemand=requirement.model, ready=readiness.ready, reason=readiness.reason,
                candidates=tuple(RuntimeResourceCandidate(runtimeId=c.resource_id, accepted=c.accepted,
                    reasons=tuple(r.value for r in c.reasons), snapshotVersion=readiness.runtime_versions[c.resource_id])
                    for c in candidates), candidateCount=len(readiness.candidates),
                nodeVersions={n: readiness.node_versions[n] for n in sorted(nodes)},
                modelEndpointVersions=dict(list(readiness.model_endpoint_versions.items())[:16]),
            ))
        failovers = tuple(RuntimeResourceFailover(stepId=item["stepId"], runtimeId=item["resourceId"])
            for item in (run.execution_state.get("resourceFailoverHistory") or [])[-16:]
            if isinstance(item, dict) and item.get("stepId") and item.get("resourceId"))
        resources = tuple(
            (p.node_id, self.resource_plane.node_health(p.node_id).status.value)
            for p in self.resource_plane.nodes()
        )
        protected = ()
        if plan is not None and run.execution_state.get("planningCommitRequired"):
            from runtime.planning_commit import protected_task_keys

            receipts = self.execution_value_store.list_node_commits(run_id=run.run_id)
            protected = tuple(sorted(protected_task_keys(run, state, plan, receipts)))
        from runtime.planning_context_catalog import build_planning_context_catalog
        context_catalog = build_planning_context_catalog(self, run, workspace_snapshot=discovery)
        return RuntimePlanningObservation(
            missionId=run.mission_id, runId=run.run_id, graphId=state.graph_id,
            graphVersion=state.graph_version, planVersion=plan.plan_version if plan else state.graph_version,
            checkpointId=state.checkpoint_id, wakeReason=reason,
            goal=basis.objective if basis is not None else self.load_goal(run.mission_id),
            missionIntentBasisRef=basis.reference() if basis is not None else None,
            steps=tuple(facts), committedResults=tuple(result_index),
            contextCatalog=context_catalog,
            remainingStepIds=remaining, protectedTaskKeys=protected,
            failureId=failure.get("failureId"), failureType=failure.get("failureType"),
            failureReason=failure.get("reasonCode"), failureSource=failure.get("source"),
            failureMessage=str(failure["message"])[:500] if failure.get("message") else None,
            failureStepId=(failure.get("details") or {}).get("stepId"),
            recoveryAction=recovery_action, readonlyRecoveryProof=readonly_recovery_proof,
            failedStepIds=failed_steps,
            completionBlockers=tuple(blockers), resources=resources,
            resourceRequirements=tuple(resource_facts), resourceFailovers=failovers,
            taskAcceptance=acceptance, taskAcceptanceResults=acceptance_results,
            workspaceObservations=workspace_progress,
            workspaceDiscovery=discovery,
            planningCommitRejection=run.execution_state.get("planningCommitRejection"),
            conditionWake=planning.waiting.wake if reason == "condition" and planning.waiting else None,
            humanAnswers=planning.human_answers,
            userInputs=planning.user_inputs,
        )

    @staticmethod
    def _verification_blockers(run, facts, *, exhausted):
        """Check the current causal frontier, not an accumulating failure log.

        A later passed verifier may supersede an earlier report only when the
        executable graph proves the dependency. An unrelated passed report or
        a final synthesizer's own assertion cannot clear a failed check.
        """
        successors = {}
        for edge in (run.acg_blueprint or {}).get("edges", ()):
            if edge.get("activation") == "terminated":
                continue
            successors.setdefault(edge["sourceId"], set()).add(edge["targetId"])
        reachable = {}
        def descendants(step_id):
            if step_id not in reachable:
                pending, seen = list(successors.get(step_id, ())), set()
                while pending:
                    current = pending.pop()
                    if current in seen:
                        continue
                    seen.add(current)
                    pending.extend(successors.get(current, ()))
                reachable[step_id] = seen
            return reachable[step_id]
        by_id = {fact.step_id: fact for fact in facts}
        steps = {step.step_id: step for step in run.steps}
        verifiers = {step.step_id for step in run.steps if step.capability == "verification"}
        passed = {step_id for step_id in verifiers
                  if by_id[step_id].output_ref and by_id[step_id].verification_report == "passed"}

        def criteria(step_id):
            # These are the frozen task obligations, not the verifier's own
            # claim that it checked them. Preserve semantic text without
            # guessing equivalence from titles, keywords or model prose.
            return {" ".join(str(item).split()).casefold()
                    for item in getattr(steps[step_id], "acceptance_criteria", ()) if str(item).strip()}

        def covers_review(previous_id, current_id):
            if current_id not in descendants(previous_id):
                return False
            previous, current = criteria(previous_id), criteria(current_id)
            if previous:
                return previous <= current
            # Truly undeclared legacy review contracts retain their causal
            # compatibility. Once a new scoped contract exists, a path alone
            # cannot prove what the old review required.
            return not current and not getattr(steps[previous_id], "source_refs", ())

        def receives_artifact(producer_id, verifier_id):
            if verifier_id not in descendants(producer_id):
                return False
            declared = getattr(steps[verifier_id], "input", {}).get("from")
            if isinstance(declared, dict) and declared:
                fields = declared.get(producer_id, ())
                return bool(set(fields) & {"deliverable", "final_answer", "artifact"})
            # Old graphs may not persist field channels. A direct producer
            # dependency is their existing data contract; an arbitrary path
            # through summaries or a final synthesizer is insufficient.
            return verifier_id in successors.get(producer_id, ())

        def covers_candidate(previous_id, current_id):
            if not covers_review(previous_id, current_id):
                return False
            candidates = {step_id for step_id, step in steps.items()
                if step.capability == "artifact_generation"
                and (step_id in descendants(previous_id) or previous_id in descendants(step_id))
                and current_id in descendants(step_id)}
            latest = {step_id for step_id in candidates
                if not (descendants(step_id) & candidates)}
            return all(receives_artifact(step_id, current_id) for step_id in latest)

        blockers = []
        for step_id in sorted(verifiers):
            report = by_id[step_id].verification_report
            if (by_id[step_id].output_ref and report in {None, "partial", "failed"}
                    and not any(covers_candidate(step_id, current_id) for current_id in passed)):
                blockers.append(f"verification_{report or 'unverified'}:{step_id}")
        if not exhausted:
            return blockers
        finals = [step.step_id for step in run.steps if step.capability == "artifact_generation"
                  and is_final_synthesis_role(step.logical_role)]
        if len(finals) > 1:
            blockers.append("final_synthesis_ambiguous")
        producers = {step.step_id for step in run.steps
                     if step.capability == "artifact_generation" and step.step_id not in finals
                     and by_id[step.step_id].output_ref}
        for final_id in finals:
            if not by_id[final_id].output_ref:
                blockers.append(f"final_output_missing:{final_id}")
            upstream = {step.step_id for step in run.steps if final_id in descendants(step.step_id)}
            latest_producers = {step_id for step_id in producers & upstream
                                if not (descendants(step_id) & producers & upstream)}
            # Do not impose a new verifier on old single-step artifact graphs.
            # Once independent verification/refinement is declared, its actual
            # passed report must cover each current producer before synthesis.
            if latest_producers:
                for producer_id in sorted(latest_producers):
                    obligations = {step_id for step_id in verifiers if producer_id in descendants(step_id)}
                    current_reviews = {current_id for current_id in passed & upstream
                        if receives_artifact(producer_id, current_id)}
                    if not current_reviews or any(not any(covers_review(previous_id, current_id)
                            for current_id in current_reviews) for previous_id in obligations):
                        blockers.append(f"final_verification_missing:{final_id}:{producer_id}")
            elif verifiers and not (passed & upstream):
                blockers.append(f"final_verification_missing:{final_id}")
        return blockers
