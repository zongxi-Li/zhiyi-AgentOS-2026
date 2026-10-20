"""Deterministic bounded frontier selection over an existing trusted TaskPlan.

The topology compiler validates the snapshot. This module only packs candidates;
it neither repairs topology nor creates an execution graph. HTN proposals are not
accepted as input: their local boundary relations are not a committed global DAG.
"""
from __future__ import annotations

import hashlib
import json
import os
from time import monotonic

from components.planner.topology.gate import validate_task_plan_for_execution
from components.planner.topology.model import EdgeOrigin
from contracts.horizon import (
    DeferredWork, FrontierTask, HorizonBoundary, HorizonBudget, HorizonProposal, PlanningFrontier,
)
from contracts.planning import SemanticTaskRelationType


def horizon_planning_enabled() -> bool:
    return os.getenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "").strip().lower() in {"1", "true", "yes", "on"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class HorizonError(ValueError):
    pass


class AdaptiveHorizonSelector:
    def __init__(self, capability_catalog, *, budget=None, monotonic_clock=monotonic):
        self.capability_catalog = capability_catalog
        self.budget = budget or HorizonBudget()
        self.monotonic = monotonic_clock

    @property
    def policy_revision(self):
        return fingerprint({"version": "adaptive-horizon.v1", "budget": self.budget.model_dump(),
            "catalog": [d.model_dump(mode="json") for d in sorted(
                self.capability_catalog.available(), key=lambda d: d.capability_id)]})

    def _deadline(self, deadline):
        if self.monotonic() > deadline:
            raise HorizonError("HORIZON_DEADLINE_EXCEEDED")

    def frontier(self, *, plan, basis, observation, run_status="running", control_barrier=False,
                 review_keys=(), deadline=float("inf")):
        self._deadline(deadline)
        policy = self.policy_revision
        # Bound raw input BEFORE invoking the sole semantic/topology authority.
        if len(plan.nodes) > 256 or len(plan.relations) > 1024:
            raise HorizonError("HORIZON_INPUT_BUDGET_EXCEEDED")
        if len(plan.model_dump_json()) + len(observation.model_dump_json()) > 300_000:
            raise HorizonError("HORIZON_CONTENT_BUDGET_EXCEEDED")
        if (basis is None or basis.mission_id != plan.mission_id
                or observation.mission_id != plan.mission_id
                or observation.plan_version != plan.plan_version
                or observation.mission_intent_basis_ref != basis.reference()
                or (plan.metadata.get("missionIntentBasisRef") is not None
                    and plan.metadata["missionIntentBasisRef"] != basis.reference())):
            raise HorizonError("HORIZON_BASIS_BINDING_MISMATCH")
        try:
            validated = validate_task_plan_for_execution(
                capability_catalog=self.capability_catalog, mission_id=plan.mission_id,
                # Canonical keys prevent incidental tuple order from choosing a
                # different implicit producer/terminal connector. Explicit edges
                # remain fixed; the compiler still owns all topology decisions.
                nodes=tuple(sorted(plan.nodes, key=lambda n: n.key)), relations=plan.relations,
                control_policies=plan.control_policies,
                expected_artifacts=plan.expected_artifacts, relation_origin=EdgeOrigin.PLAN_PATCH,
                plan_version=plan.plan_version, metadata=plan.metadata)
        except (ValueError, KeyError) as exc:
            raise HorizonError("HORIZON_TOPOLOGY_REJECTED") from exc
        self._deadline(deadline)
        dependencies = tuple(sorted((r for r in validated.relations
            if r.relation_type == SemanticTaskRelationType.DEPENDS_ON),
            key=lambda r: (r.source_key, r.target_key)))
        if len(dependencies) > 4096:
            raise HorizonError("HORIZON_EDGE_BUDGET_EXCEEDED")
        by_key = {}
        review_keys = frozenset(review_keys)
        if not review_keys <= {n.key for n in plan.nodes}:
            raise HorizonError("HORIZON_INVALID_REVIEW_BINDING")
        for step in observation.steps:
            if step.task_key in by_key:
                raise HorizonError("HORIZON_AMBIGUOUS_EXECUTION_STATE")
            by_key[step.task_key] = step
        risk_values = {"normal": 1, "elevated": 2, "high": 4, "critical": 8}
        tasks = []
        for node in sorted(plan.nodes, key=lambda n: n.key):
            self._deadline(deadline)
            descriptors = [self.capability_catalog.resolve(c) for c in node.capability_requirements]
            risks = [risk_values[str(d.risk_level_hint)] for d in descriptors]
            metadata_risk = node.metadata.get("risk", "normal")
            if not isinstance(metadata_risk, str) or metadata_risk not in risk_values:
                raise HorizonError("HORIZON_UNKNOWN_RISK")
            risk = max([risk_values[metadata_risk], *risks])
            work_units = (node.workset.estimated_unit_count or 0) if node.workset else 0
            cost = max(1, len(descriptors), work_units)
            step = by_key.get(node.key)
            status = step.status if step else "unknown"
            resources = [r for r in observation.resource_requirements if step and r.step_id == step.step_id]
            readiness = "not_ready" if any(not r.ready for r in resources) else "observed_ready" if resources else "unknown"
            if status == "completed":
                # No completed work is ever reconsidered, including missing receipts.
                cls = "completed" if (step.output_ref and step.commit_id and step.audit_ref and step.audit_outcome in {"allow", "review"}
                    and f"review_unresolved:{step.step_id}" not in observation.completion_blockers
                    and (not any(d.capability_id == "verification" for d in descriptors)
                         or step.verification_report == "passed")
                    and step.verification_report not in {"partial", "failed"}) else "unknown"
            elif status in {"running", "retrying"}:
                cls = "active"
            elif status == "waiting_review" or (step and step.audit_outcome in {"review", "deny"}):
                cls = "review_wait"
            elif status == "failed":
                cls = "failed"
            elif status in {"cancelled", "skipped_by_condition"}:
                cls = "terminal"
            elif status != "pending":
                cls = "unknown"
            elif step.commit_id or step.audit_ref:
                cls = "unknown"  # pending with execution evidence is not safe new work
            elif step.step_id not in observation.remaining_step_ids:
                cls = "unknown"  # a pending label alone cannot recreate settled work
            elif observation.completion_blockers or run_status == "waiting_review":
                cls = "review_wait"
            elif run_status in {"completed", "failed", "cancelled", "superseded"}:
                cls = "terminal"
            elif plan.control_policies or control_barrier:
                cls = "control_wait"  # loop iteration authority remains with Runtime
            elif readiness == "not_ready":
                cls = "resource_wait"
            else:
                cls = "considerable"
            tasks.append(FrontierTask(key=node.key, status=status, classification=cls,
                riskUnits=risk, costUnits=cost,
                requiresReview=node.key in review_keys or any(d.requires_review for d in descriptors),
                readiness=readiness, taskFingerprint=fingerprint(node.model_dump(mode="json", by_alias=True))))
        completed = {t.key for t in tasks if t.classification == "completed"}
        tasks = tuple(t.model_copy(update={
            "unmet_dependencies": tuple(sorted({r.source_key for r in dependencies
                if r.target_key == t.key and r.source_key not in completed})),
            "classification": "dependency_blocked" if t.classification == "considerable" and any(
                r.target_key == t.key and r.source_key not in completed for r in dependencies) else t.classification,
        }) for t in tasks)
        if policy != self.policy_revision:
            raise HorizonError("HORIZON_POLICY_CHANGED")
        inputs = fingerprint({"plan": plan.model_dump(mode="json", by_alias=True),
            "basis": basis.fingerprint, "observation": observation.fingerprint(), "policy": policy,
            "runStatus": run_status, "controlBarrier": bool(control_barrier or plan.control_policies),
            "reviewKeys": sorted(review_keys)})
        self._deadline(deadline)
        return PlanningFrontier(missionId=plan.mission_id, basisFingerprint=basis.fingerprint,
            observationId=observation.fingerprint(), planVersion=plan.plan_version, runStatus=run_status,
            policyRevision=policy, inputFingerprint=inputs, tasks=tasks,
            dependencies=dependencies, budget=self.budget, controlBarrier=bool(control_barrier or plan.control_policies))

    def propose(self, *, plan, basis, observation, run_status="running", control_barrier=False,
                review_keys=(), selected_keys=None, input_fingerprint=None, deadline=float("inf")):
        frontier = self.frontier(plan=plan, basis=basis, observation=observation, run_status=run_status,
            control_barrier=control_barrier, review_keys=review_keys, deadline=deadline)
        if input_fingerprint is not None and input_fingerprint != frontier.input_fingerprint:
            raise HorizonError("HORIZON_STALE_INPUT")
        tasks = {t.key: t for t in frontier.tasks}
        completed = {t.key for t in frontier.tasks if t.classification == "completed"}
        pending = {t.key for t in frontier.tasks if t.classification in {"considerable", "dependency_blocked"}}
        selected, reasons = [], {}
        selected_set = set()
        outdegree = {key: 0 for key in tasks}
        for relation in frontier.dependencies:
            outdegree[relation.source_key] += 1
        unmet = {key: set(task.unmet_dependencies) for key, task in tasks.items()}
        cost = risk = 0
        barrier = None
        while pending:
            self._deadline(deadline)
            feasible = [tasks[k] for k in pending if unmet[k] <= selected_set]
            if not feasible:
                break
            feasible.sort(key=lambda t: (t.risk_units,
                -outdegree[t.key], t.cost_units, t.key))
            t = feasible[0]
            pending.remove(t.key)
            if barrier:
                reasons[t.key] = barrier
                continue
            if (cost + t.cost_units > self.budget.cost_units or risk + t.risk_units > self.budget.risk_units
                    or len(selected) >= self.budget.max_candidates):
                reasons[t.key] = "budget"
                continue
            # High risk work is isolated; no speculative work past an approval boundary.
            if t.risk_units >= 4 and selected:
                reasons[t.key] = "risk_boundary"
                continue
            selected.append(t.key)
            selected_set.add(t.key)
            cost += t.cost_units
            risk += t.risk_units
            if t.requires_review or t.risk_units >= 4:
                barrier = "review_boundary" if t.requires_review else "risk_boundary"
        model_subset = selected_keys is not None
        if model_subset:
            if len(selected_keys) != len(set(selected_keys)) or not set(selected_keys) <= set(selected):
                raise HorizonError("HORIZON_SELECTION_OUTSIDE_CANDIDATES")
            subset = set(selected_keys)
            if any(not set(tasks[k].unmet_dependencies) <= subset for k in subset):
                raise HorizonError("HORIZON_SELECTION_DEPENDENCY_GAP")
            selected = [k for k in selected if k in subset]
        chosen = set(selected)
        deferred = tuple(DeferredWork(key=t.key, reason=(
            "model_deferred" if model_subset and t.key not in pending and t.key not in reasons
            and t.classification in {"considerable", "dependency_blocked"} else
            reasons.get(t.key, "dependency_boundary" if t.classification == "dependency_blocked" else
                "budget" if t.classification == "considerable" else t.classification)))
            for t in frontier.tasks if t.key not in chosen and t.key not in completed)
        internal = tuple(r for r in frontier.dependencies if r.source_key in chosen and r.target_key in chosen)
        boundary = tuple(HorizonBoundary(relation=r, prerequisiteCompleted=r.source_key in completed)
            for r in frontier.dependencies if (r.source_key in chosen) != (r.target_key in chosen))
        self._deadline(deadline)
        if frontier.policy_revision != self.policy_revision:
            raise HorizonError("HORIZON_POLICY_CHANGED")
        return HorizonProposal(frontier=frontier, candidateKeys=tuple(selected),
            readyKeys=tuple(k for k in selected if not tasks[k].unmet_dependencies), deferred=deferred,
            internalDependencies=internal, crossWindowDependencies=boundary,
            usedCostUnits=sum(tasks[k].cost_units for k in selected),
            usedRiskUnits=sum(tasks[k].risk_units for k in selected),
            selectionBasis="bounded_model_subset" if model_subset else "risk_then_unblocking_then_cost")
