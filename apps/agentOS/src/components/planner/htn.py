"""Bounded HTN selection/expansion, with no store or execution authority."""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic

from contracts.htn import (HTNCondition, HTNExpansionProposal, HTNMethod,
                           HTNMethodCandidate, HTNMethodCatalogProjection, HTNMethodSelection,
                           HTNSubtask)
from contracts.mission_semantic import MissionIntentBasis
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningObservation
from .topology import EdgeOrigin, validate_task_plan_for_execution


def htn_planning_enabled() -> bool:
    return os.getenv("AGENTOS_PLANNER_HTN", "").strip().lower() in {"1", "true", "yes", "on"}


class HTNError(ValueError):
    def __init__(self, code: str):
        self.code = code
        # No mission text, model rationale or definition payload in errors/audit.
        super().__init__(code)


@dataclass(frozen=True)
class HTNBudget:
    max_depth: int = 8
    max_nodes: int = 64
    max_relations: int = 256
    max_candidates: int = 256
    max_content_chars: int = 120_000

    def __post_init__(self):
        if any(value < 1 for value in vars(self).values()):
            raise ValueError("HTN budgets must be positive")


@dataclass(frozen=True, init=False)
class HTNMethodCatalog:
    """Immutable serialized snapshot; callers cannot mutate nested task dictionaries."""
    _definitions: tuple[str, ...]
    revision: str

    def __init__(self, methods):
        definitions = [HTNMethod.model_validate(m.model_dump(by_alias=True)) for m in methods]
        if len(definitions) > 128 or len({m.method_id for m in definitions}) != len(definitions):
            raise ValueError("method catalog is bounded and methodIds must be unique")
        serialized = tuple(json.dumps(m.model_dump(by_alias=True, mode="json"),
                                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                           for m in sorted(definitions, key=lambda m: m.method_id))
        if sum(map(len, serialized)) > 120_000:
            raise ValueError("method catalog content budget exceeded")
        object.__setattr__(self, "_definitions", serialized)
        object.__setattr__(self, "revision", hashlib.sha256(
            json.dumps(serialized, ensure_ascii=False).encode()).hexdigest())

    def methods(self) -> tuple[HTNMethod, ...]:
        return tuple(HTNMethod.model_validate_json(item) for item in self._definitions)


class HTNMethodSelector:
    def __init__(self, *, catalog: HTNMethodCatalog, capability_catalog, budget: HTNBudget | None = None):
        self.catalog = catalog
        self.capability_catalog = capability_catalog
        self.budget = budget or HTNBudget()

    @staticmethod
    def _validate_constraint_sources(task: PlannedTask, allowed_sources: set[str]) -> None:
        for constraint in task.constraints:
            refs = constraint.get("sourceRefs", ())
            if (not isinstance(refs, (list, tuple))
                    or any(not isinstance(ref, str) or ref not in allowed_sources for ref in refs)):
                raise HTNError("HTN_UNKNOWN_SOURCE")

    @staticmethod
    def _constraints(basis: MissionIntentBasis, task: PlannedTask) -> dict[str, str]:
        constraints = {c.constraint_id: c.text for c in basis.constraints}
        for item in task.constraints:
            key = item.get("constraintId")
            text = item.get("value", item.get("text"))
            if key is not None:
                if not isinstance(key, str) or not isinstance(text, str):
                    raise HTNError("HTN_CONSTRAINT_CONFLICT")
                if key in constraints and constraints[key] != text:
                    raise HTNError("HTN_CONSTRAINT_CONFLICT")
                constraints[key] = text
        return constraints

    def _context(self, *, plan, target_key, basis, observation):
        if basis is None:
            raise HTNError("HTN_BASIS_REQUIRED")
        basis = MissionIntentBasis.model_validate(basis.model_dump(by_alias=True))
        if (basis.mission_id != plan.mission_id or observation.mission_id != plan.mission_id
                or observation.plan_version != plan.plan_version
                or observation.mission_intent_basis_ref != basis.reference()):
            raise HTNError("HTN_BINDING_MISMATCH")
        target = next((n for n in plan.nodes if n.key == target_key), None)
        if target is None or not target.metadata.get("taskType"):
            raise HTNError("HTN_UNKNOWN_ABSTRACT_TASK")
        if target.workset is not None:
            raise HTNError("HTN_WORKSET_UNSUPPORTED")
        # Existing hierarchies and controls need S02's prefix-preservation rules.
        descendants = {target_key}
        for _ in plan.nodes:
            descendants.update(n.key for n in plan.nodes if n.parent_key in descendants)
        if (len(descendants) > 1 or target.parent_key is not None
                or any(e.relation_type.value == "parent" and target_key in {e.source_key, e.target_key}
                       for e in plan.relations)):
            raise HTNError("HTN_EXISTING_HIERARCHY")
        if any(target_key in {p.body_entry_key, p.body_exit_key, p.condition_source_key}
               for p in plan.control_policies):
            raise HTNError("HTN_CONTROLLED_TASK")
        facts = [s for s in observation.steps if s.task_key in descendants]
        if (not facts or any(s.status not in {"pending", "ready"} or s.commit_id or s.audit_ref
                             for s in facts)):
            raise HTNError("HTN_SETTLED_OR_ACTIVE_TASK")
        if not target.source_refs:
            raise HTNError("HTN_SOURCE_REQUIRED")
        allowed_sources = set(basis.source_references) | {f"basis:{basis.fingerprint}"}
        allowed_sources.update(ref for c in basis.constraints for ref in c.source_refs)
        if not set(target.source_refs) <= allowed_sources:
            raise HTNError("HTN_UNKNOWN_SOURCE")
        self._validate_constraint_sources(target, allowed_sources)
        self._constraints(basis, target)
        return target, basis

    @staticmethod
    def _matches(condition: HTNCondition, basis, task, observation, constraints):
        if condition.source == "basis_source_type":
            fact = basis.source_type
        elif condition.source == "constraint":
            fact = constraints.get(condition.key)
        elif condition.source == "wake_reason":
            fact = observation.wake_reason
        else:
            matches = [s for s in observation.steps if s.task_key == condition.key]
            # Ambiguous/missing observations are not execution facts.
            if len(matches) != 1:
                return False
            fact = matches[0].status if condition.source == "step_status" else matches[0].audit_outcome
        return fact is not None and fact == condition.equals

    def _candidates(self, abstract_task, task, basis, observation, counter, methods=None):
        constraints = self._constraints(basis, task)
        candidates = []
        for method in sorted(methods if methods is not None else self.catalog.methods(), key=lambda m: (m.priority, m.method_id)):
            if method.abstract_task != abstract_task:
                continue
            counter[0] += 1
            if counter[0] > self.budget.max_candidates:
                raise HTNError("HTN_BUDGET_EXHAUSTED")
            reason = "APPLICABLE"
            if not all(self._matches(c, basis, task, observation, constraints) for c in method.applicability):
                reason = "CONDITION_NOT_MET"
            try:
                for slot in method.subtasks:
                    for capability in slot.task.capability_requirements:
                        self.capability_catalog.resolve(capability)
            except KeyError:
                reason = "CAPABILITY_UNAVAILABLE"
            candidates.append((method, reason))
        return candidates

    def query(self, *, plan, target_key, basis, observation) -> HTNMethodCatalogProjection:
        catalog = self.catalog
        target, basis = self._context(plan=plan, target_key=target_key, basis=basis, observation=observation)
        candidates = self._candidates(target.metadata["taskType"], target, basis, observation, [0], catalog.methods())
        if not candidates:
            raise HTNError("HTN_NO_METHOD")
        return HTNMethodCatalogProjection(targetKey=target_key, catalogRevision=catalog.revision,
            candidates=tuple(HTNMethodCandidate(methodId=m.method_id, abstractTask=m.abstract_task,
                version=m.version, applicable=reason == "APPLICABLE", reason=reason,
                sourceRefs=m.source_refs, applicability=m.applicability,
                subtasks=m.subtasks, ordering=m.ordering) for m, reason in candidates))

    def expand(self, *, plan, target_key, basis, observation, method_id, catalog_revision,
               preferred_method_ids=(), deadline: float | None = None) -> HTNExpansionProposal:
        catalog = self.catalog
        methods = catalog.methods()
        if catalog_revision != catalog.revision:
            raise HTNError("HTN_CATALOG_CHANGED")
        target, basis = self._context(plan=plan, target_key=target_key, basis=basis, observation=observation)
        defined = {m.method_id for m in methods}
        if method_id not in defined or set(preferred_method_ids) - defined:
            raise HTNError("HTN_UNKNOWN_METHOD")
        nodes: list[PlannedTask] = []
        edges: list[TaskPlanRelation] = []
        leaves: list[PlannedTask] = []
        selections = []
        counter = [0]
        used_keys = {target_key}
        existing_keys = {n.key for n in plan.nodes} - {target_key}
        content_chars = 0

        def check_budget():
            if (len(nodes) > self.budget.max_nodes or len(edges) > self.budget.max_relations
                    or content_chars > self.budget.max_content_chars
                    or (deadline is not None and monotonic() > deadline)):
                raise HTNError("HTN_BUDGET_EXHAUSTED")

        def visit(task, abstract_task, stack, depth, requested=None):
            nonlocal content_chars
            check_budget()
            if depth > self.budget.max_depth:
                raise HTNError("HTN_BUDGET_EXHAUSTED")
            if abstract_task is not None and abstract_task in stack:
                raise HTNError("HTN_EXPANSION_CYCLE")
            self._constraints(basis, task)
            nodes.append(task)
            content_chars += len(task.model_dump_json())
            check_budget()
            if abstract_task is None:
                leaves.append(task)
                return (task.key,)
            candidates = self._candidates(abstract_task, task, basis, observation, counter, methods)
            legal = [m for m, reason in candidates if reason == "APPLICABLE"]
            if requested is not None:
                method = next((m for m in legal if m.method_id == requested), None)
                if method is None:
                    raise HTNError("HTN_METHOD_NOT_APPLICABLE")
            else:
                rank = {key: i for i, key in enumerate(preferred_method_ids)}
                legal.sort(key=lambda m: (rank.get(m.method_id, len(rank)), m.priority, m.method_id))
                if not legal:
                    raise HTNError("HTN_NO_APPLICABLE_METHOD")
                method = legal[0]
            selections.append(HTNMethodSelection(taskKey=task.key, abstractTask=abstract_task,
                methodId=method.method_id, methodVersion=method.version))
            groups = {}
            for slot in method.subtasks:
                # Identity depends on the semantic parent + stable method/slot, never text,
                # action/session/run IDs, catalog content checksum or mutable version.
                key = "htn:" + hashlib.sha256(json.dumps(
                    [task.key, method.method_id, slot.task.key], separators=(",", ":")).encode()).hexdigest()[:32]
                if key in used_keys or key in existing_keys:
                    raise HTNError("HTN_KEY_COLLISION")
                used_keys.add(key)
                child = PlannedTask.model_validate({**slot.task.model_dump(by_alias=True),
                    "key": key, "parentKey": task.key,
                    "constraints": deepcopy([*task.constraints, *slot.task.constraints]),
                    "acceptanceCriteria": tuple(dict.fromkeys((*task.acceptance_criteria, *slot.task.acceptance_criteria))),
                    "sourceRefs": tuple(dict.fromkeys((*task.source_refs, *method.source_refs, *slot.task.source_refs))),
                })
                # Slot sources may only cite inherited inputs or the trusted definition.
                if not set(slot.task.source_refs) <= set(task.source_refs) | set(method.source_refs):
                    raise HTNError("HTN_UNKNOWN_SOURCE")
                self._validate_constraint_sources(child, set(child.source_refs))
                groups[slot.task.key] = visit(child, slot.abstract_task, (*stack, abstract_task), depth + 1)
                edges.append(TaskPlanRelation(sourceKey=task.key, targetKey=key, relationType="parent"))
                check_budget()
            for ordering in method.ordering:
                for source in groups[ordering.source_key]:
                    for destination in groups[ordering.target_key]:
                        edges.append(TaskPlanRelation(sourceKey=source, targetKey=destination, relationType="depends_on"))
                        check_budget()
            return tuple(key for group in groups.values() for key in group)

        inherited = [dict(type="mission_constraint", constraintId=c.constraint_id,
                          value=c.text, sourceRefs=list(c.source_refs)) for c in basis.constraints]
        root = PlannedTask.model_validate({**target.model_dump(by_alias=True),
            "parentKey": None, "capabilityRequirements": (), "workset": None,
            "producedArtifacts": (), "constraints": deepcopy([*inherited, *target.constraints]),
            "sourceRefs": tuple(dict.fromkeys((*target.source_refs, *basis.source_references,
                *(ref for c in basis.constraints for ref in c.source_refs))))})
        visit(root, target.metadata["taskType"], (), 0, method_id)
        # Shared semantic/topology authority validates *atomic* work. Parents are
        # explanatory nodes, never fake capability producers or executable sinks.
        atomic = [PlannedTask.model_validate({**n.model_dump(by_alias=True), "parentKey": None}) for n in leaves]
        try:
            validated = validate_task_plan_for_execution(
                capability_catalog=self.capability_catalog, mission_id=plan.mission_id,
                plan_version=plan.plan_version, nodes=atomic,
                relations=[e for e in edges if e.relation_type.value == "depends_on"],
                expected_artifacts=target.produced_artifacts,
                relation_origin=EdgeOrigin.TEMPLATE_DECLARED, producer_kind="htn_proposal")
            edges = [e for e in edges if e.relation_type.value == "parent"] + list(validated.relations)
            # Also validate the hierarchy with the existing TaskPlan contract.
            TaskPlan(missionId=plan.mission_id, planVersion=plan.plan_version,
                     nodes=tuple(n for n in plan.nodes if n.key != target_key) + tuple(nodes),
                     relations=tuple(plan.relations) + tuple(edges), controlPolicies=plan.control_policies,
                     expectedArtifacts=plan.expected_artifacts)
        except ValueError as exc:
            raise HTNError("HTN_TOPOLOGY_INVALID") from exc
        required = {self.capability_catalog.resolve(c).capability_id for c in target.capability_requirements}
        supplied = {self.capability_catalog.resolve(c).capability_id
                    for leaf in leaves for c in leaf.capability_requirements}
        if not required <= supplied:
            raise HTNError("HTN_CAPABILITY_REQUIREMENT_LOST")
        check_budget()
        if self.catalog.revision != catalog.revision:
            raise HTNError("HTN_CATALOG_CHANGED")
        return HTNExpansionProposal(targetKey=target_key, catalogRevision=catalog.revision,
            basisFingerprint=basis.fingerprint, observationId=observation.fingerprint(),
            basePlanVersion=plan.plan_version, nodes=tuple(nodes), relations=tuple(edges),
            boundaryRelations=tuple(e for e in plan.relations if target_key in {e.source_key, e.target_key}),
            atomicKeys=tuple(n.key for n in leaves), selections=tuple(selections))


def build_native_htn_catalog() -> HTNMethodCatalog:
    """Small, core-owned runnable vocabulary; injected registries can extend it."""
    def slot(key, capability=None, abstract=None):
        return HTNSubtask(task=PlannedTask(key=key, title=key, objective=f"Produce traceable {key}",
            capabilityRequirements=(capability,) if capability else (),
            acceptanceCriteria=("Result is traceable to cited input sources.",)), abstractTask=abstract)

    def order(source, target):
        return TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")

    return HTNMethodCatalog((
        HTNMethod(methodId="analysis.standard", abstractTask="analysis", priority=10,
            subtasks=(slot("understand", "task_understanding"), slot("analyze", "analysis")),
            ordering=(order("understand", "analyze"),), sourceRefs=("htn:native:analysis.standard",)),
        HTNMethod(methodId="analysis.evidence", abstractTask="analysis", priority=0,
            applicability=(HTNCondition(source="basis_source_type", equals="SEMANTIC"),),
            subtasks=(slot("understand", "task_understanding"), slot("research", abstract="evidence")),
            ordering=(order("understand", "research"),), sourceRefs=("htn:native:analysis.evidence",)),
        HTNMethod(methodId="evidence.compare", abstractTask="evidence",
            subtasks=(slot("retrieve", "information_retrieval"), slot("evaluate", "evidence_analysis"),
                      slot("compare", "comparative_analysis")),
            ordering=(order("retrieve", "evaluate"), order("evaluate", "compare")),
            sourceRefs=("htn:native:evidence.compare",)),
    ))
