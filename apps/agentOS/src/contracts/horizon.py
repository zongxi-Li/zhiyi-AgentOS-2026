"""S01-04 read-only planning candidates; never an execution commitment."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.identity import SemanticTaskKey
from contracts.planning import TaskPlanRelation


class HorizonContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class HorizonBudget(HorizonContract):
    # Conservative planning units, not money, capacity reservations or execution quotas.
    cost_units: int = Field(default=12, ge=1, le=1024, alias="costUnits")
    risk_units: int = Field(default=8, ge=1, le=1024, alias="riskUnits")
    max_candidates: int = Field(default=16, ge=1, le=64, alias="maxCandidates")


FrontierClass = Literal[
    "completed", "active", "considerable", "dependency_blocked", "review_wait",
    "failed", "terminal", "unknown", "resource_wait", "control_wait",
]


class FrontierTask(HorizonContract):
    key: SemanticTaskKey
    status: str
    classification: FrontierClass
    unmet_dependencies: tuple[SemanticTaskKey, ...] = Field(default=(), alias="unmetDependencies")
    risk_units: int = Field(ge=1, alias="riskUnits")
    cost_units: int = Field(ge=1, alias="costUnits")
    requires_review: bool = Field(alias="requiresReview")
    readiness: Literal["observed_ready", "not_ready", "unknown"]
    task_fingerprint: str = Field(min_length=64, max_length=64, alias="taskFingerprint")


class PlanningFrontier(HorizonContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    algorithm_version: Literal["adaptive-horizon.v1"] = Field(default="adaptive-horizon.v1", alias="algorithmVersion")
    input_kind: Literal["formal_task_plan"] = Field(default="formal_task_plan", alias="inputKind")
    mission_id: str = Field(alias="missionId")
    basis_fingerprint: str = Field(min_length=64, max_length=64, alias="basisFingerprint")
    observation_id: str = Field(min_length=64, max_length=64, alias="observationId")
    plan_version: int = Field(ge=1, alias="planVersion")
    run_status: str = Field(alias="runStatus")
    control_barrier: bool = Field(default=False, alias="controlBarrier")
    policy_revision: str = Field(min_length=64, max_length=64, alias="policyRevision")
    input_fingerprint: str = Field(min_length=64, max_length=64, alias="inputFingerprint")
    tasks: tuple[FrontierTask, ...] = Field(max_length=256)
    dependencies: tuple[TaskPlanRelation, ...] = Field(max_length=4096)
    budget: HorizonBudget
    validation_scope: Literal["task_plan_snapshot_only"] = Field(default="task_plan_snapshot_only", alias="validationScope")

    @model_validator(mode="after")
    def closed_snapshot(self):
        keys = {t.key for t in self.tasks}
        if len(keys) != len(self.tasks):
            raise ValueError("frontier task keys must be unique")
        if any(r.relation_type.value != "depends_on" or r.source_key not in keys or r.target_key not in keys
               for r in self.dependencies):
            raise ValueError("frontier dependencies must refer to its trusted task snapshot")
        completed = {t.key for t in self.tasks if t.classification == "completed"}
        for task in self.tasks:
            unmet = {r.source_key for r in self.dependencies if r.target_key == task.key and r.source_key not in completed}
            if len(task.unmet_dependencies) != len(set(task.unmet_dependencies)) or set(task.unmet_dependencies) != unmet:
                raise ValueError("frontier must retain every unfinished dependency")
            if ((task.classification == "considerable" and unmet)
                    or (task.classification == "dependency_blocked" and not unmet)):
                raise ValueError("frontier readiness must agree with dependency facts")
        return self


class DeferredWork(HorizonContract):
    key: SemanticTaskKey
    reason: Literal["budget", "model_deferred", "dependency_boundary", "review_boundary", "risk_boundary"] | FrontierClass


class HorizonBoundary(HorizonContract):
    relation: TaskPlanRelation
    prerequisite_completed: bool = Field(alias="prerequisiteCompleted")


class HorizonProposal(HorizonContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    frontier: PlanningFrontier
    candidate_keys: tuple[SemanticTaskKey, ...] = Field(max_length=64, alias="candidateKeys")
    ready_keys: tuple[SemanticTaskKey, ...] = Field(max_length=64, alias="readyKeys")
    deferred: tuple[DeferredWork, ...] = Field(max_length=256)
    internal_dependencies: tuple[TaskPlanRelation, ...] = Field(max_length=4096, alias="internalDependencies")
    cross_window_dependencies: tuple[HorizonBoundary, ...] = Field(max_length=4096, alias="crossWindowDependencies")
    used_cost_units: int = Field(ge=0, alias="usedCostUnits")
    used_risk_units: int = Field(ge=0, alias="usedRiskUnits")
    selection_basis: Literal["risk_then_unblocking_then_cost", "bounded_model_subset"] = Field(alias="selectionBasis")
    reservation_status: Literal["not_reserved"] = Field(default="not_reserved", alias="reservationStatus")

    @model_validator(mode="after")
    def bounded_selection(self):
        # Set/budget consistency only. DAG/capability validation remains the compiler's job.
        tasks = {t.key: t for t in self.frontier.tasks}
        chosen = set(self.candidate_keys)
        if len(chosen) != len(self.candidate_keys) or not chosen <= tasks.keys():
            raise ValueError("Horizon candidates must uniquely reference frontier tasks")
        if any(tasks[k].classification not in {"considerable", "dependency_blocked"}
               or not set(tasks[k].unmet_dependencies) <= chosen for k in chosen):
            raise ValueError("Horizon selection must retain unfinished prerequisites")
        ready = {k for k in chosen if not tasks[k].unmet_dependencies}
        if len(self.ready_keys) != len(set(self.ready_keys)) or set(self.ready_keys) != ready:
            raise ValueError("readyKeys must reflect actual completed prerequisites")
        deferred = {d.key for d in self.deferred}
        completed = {t.key for t in self.frontier.tasks if t.classification == "completed"}
        if len(deferred) != len(self.deferred) or deferred != tasks.keys() - chosen - completed:
            raise ValueError("Horizon must account for every noncompleted deferred task")
        cost, risk = sum(tasks[k].cost_units for k in chosen), sum(tasks[k].risk_units for k in chosen)
        budget = self.frontier.budget
        if (cost != self.used_cost_units or risk != self.used_risk_units or cost > budget.cost_units
                or risk > budget.risk_units or len(chosen) > budget.max_candidates):
            raise ValueError("Horizon exceeds its trusted budget")
        internal = tuple(r for r in self.frontier.dependencies if r.source_key in chosen and r.target_key in chosen)
        crossing = tuple(r for r in self.frontier.dependencies if (r.source_key in chosen) != (r.target_key in chosen))
        if self.internal_dependencies != internal or tuple(b.relation for b in self.cross_window_dependencies) != crossing:
            raise ValueError("Horizon must preserve all internal and cross-window dependencies")
        if any(b.prerequisite_completed != (b.relation.source_key in completed) for b in self.cross_window_dependencies):
            raise ValueError("Horizon cannot invent completed boundary prerequisites")
        return self


class HorizonSelection(HorizonContract):
    kind: Literal["horizon"] = "horizon"
    input_fingerprint: str = Field(min_length=64, max_length=64, alias="inputFingerprint")
    selected_keys: tuple[SemanticTaskKey, ...] = Field(default=(), max_length=64, alias="selectedKeys")
