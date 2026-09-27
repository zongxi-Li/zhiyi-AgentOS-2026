"""Application service for TaskPlan-first semantic Run replacement."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from components.executor import (
    ACGExecutionState,
    ACGGraphCompiler,
    GraphPatchConflictError,
)
from components.planner.acg_semantic_validator import validate_bound_acg_semantics
from contracts.compiled_acg import CompiledACGPackage
from contracts.execution import WorkflowProgressPhase
from contracts.planning import TaskImplementationBinding, TaskPlan
from contracts.recovery import (
    GraphPatchRef,
    GraphPatchResult,
    SemanticPatchRequest,
)
from contracts.workflow import (
    GraphRef,
    RunExecutionScope,
    RuntimeMissionRecord,
    RuntimeRunRecord,
    TraceEventType,
    WorkflowDefinition,
    WorkflowStatus,
    utc_now,
)
from support.acg.schema import RuntimeBlueprintSpec
from runtime.ports import CollaboratorAccess, RuntimeCollaborators

from runtime.semantic_patch import SemanticGraphPatchService, derive_graph_patch


@dataclass(frozen=True)
class PreparedSemanticRevision:
    request: SemanticPatchRequest
    request_checksum: str
    source_run: RuntimeRunRecord
    replacement_run: RuntimeRunRecord
    task: RuntimeMissionRecord
    workflow: WorkflowDefinition
    scope: RunExecutionScope
    blueprint: RuntimeBlueprintSpec
    next_plan: TaskPlan
    next_bindings: tuple[TaskImplementationBinding, ...]
    compiled_package: CompiledACGPackage
    topology_audits: tuple[dict[str, Any], ...]


class SemanticRevisionService(CollaboratorAccess):
    """Prepare and atomically persist one canonical semantic revision."""

    def __init__(
        self,
        *,
        collaborators: RuntimeCollaborators,
        load_mission: Callable[[str], RuntimeMissionRecord],
        load_workflow: Callable[[RuntimeRunRecord], WorkflowDefinition],
        sync_run_steps: Callable[[RuntimeRunRecord, RuntimeBlueprintSpec], None],
        validate_blueprint_agents: Callable[..., None],
        replacement_lifecycle_message: str,
    ) -> None:
        self.ports = collaborators
        self.load_mission = load_mission
        self.load_workflow = load_workflow
        self.sync_run_steps = sync_run_steps
        self.validate_blueprint_agents = validate_blueprint_agents
        self.replacement_lifecycle_message = replacement_lifecycle_message

    def prepare(
        self,
        *,
        request: SemanticPatchRequest,
        run: RuntimeRunRecord,
    ) -> GraphPatchResult | PreparedSemanticRevision:
        """Validate and compile a replacement without persisting the transition."""

        if (run.runtime_engine or "").strip().lower() != "acg":
            raise ValueError("semantic patching is only available for ACG runs")
        if run.status is not WorkflowStatus.WAITING_REVIEW:
            raise GraphPatchConflictError(
                "semantic patches require a persisted WAITING_REVIEW barrier"
            )
        if not isinstance(run.acg_blueprint, dict):
            raise ValueError("ACG run has no persisted blueprint")
        checkpoint_id = str(run.execution_state.get("checkpointId") or "")
        checkpoint_data = self.checkpoint_store.load(
            run_id=run.run_id,
            checkpoint_id=checkpoint_id,
        )
        if checkpoint_data is None:
            raise ValueError("semantic patch requires a persisted checkpoint")
        state = ACGExecutionState.model_validate(checkpoint_data)
        blueprint = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)

        applied_log = list(blueprint.metadata.get("appliedGraphPatches") or [])
        previous = next(
            (
                item for item in applied_log
                if isinstance(item, dict) and item.get("patchId") == request.patch_id
            ),
            None,
        )
        request_checksum = request.checksum()
        if previous is not None:
            if str(previous.get("requestChecksum") or "") != request_checksum:
                raise GraphPatchConflictError(
                    "semantic patch id already exists with different content: "
                    f"{request.patch_id}"
                )
            uri = str(previous.get("patchRef") or "")
            if not uri:
                raise ValueError("persisted graph patch is missing its reference")
            return GraphPatchResult(
                applied=False,
                idempotentReplay=True,
                graphVersion=int(previous["graphVersion"]),
                runId=str(previous.get("newRunId") or "") or None,
                patchRef=GraphPatchRef(
                    patchId=request.patch_id,
                    graph=GraphRef(
                        graphId=blueprint.graph_id,
                        version=str(previous["graphVersion"]),
                    ),
                    uri=uri,
                    checksum=str(previous["checksum"]),
                ),
            )
        if request.graph_id != blueprint.graph_id:
            raise GraphPatchConflictError(
                "semantic patch graphId does not match blueprint"
            )
        if request.base_graph_version != blueprint.version:
            raise GraphPatchConflictError(
                f"semantic patch version {request.base_graph_version} does not "
                f"match current version {blueprint.version}"
            )
        if set(state.active_step_ids):
            raise GraphPatchConflictError(
                "semantic patch cannot be applied while nodes are active"
            )

        task = self.load_mission(run.mission_id)
        workflow = self.load_workflow(run)
        scope = run.execution_scope
        if scope is None:
            raise ValueError("semantic patch requires a frozen execution scope")
        if self.identity_lifecycle is None:
            raise ValueError("semantic patch requires the identity lifecycle adapter")

        raw_plan = run.execution_state.get("taskPlan")
        raw_bindings = run.execution_state.get("taskBindings")
        if not isinstance(raw_plan, dict) or not isinstance(raw_bindings, list):
            raise ValueError("semantic patch requires persisted Planner identity data")
        current_plan = TaskPlan.model_validate(raw_plan)
        base_bindings = tuple(
            TaskImplementationBinding.model_validate(item)
            for item in raw_bindings
        )
        topology_audits: list[dict[str, Any]] = []
        semantic_result = SemanticGraphPatchService().apply(
            blueprint=blueprint,
            request=request,
            current_plan=current_plan,
            base_bindings=base_bindings,
            agent_registry=self.agent_registry.scoped(scope.agent_ids),
            domain=workflow.domain or task.domain,
            capability_catalog=self.capability_catalog,
            audit_sink=topology_audits.append,
        )
        outcome_blueprint = semantic_result.blueprint
        next_plan = semantic_result.next_plan
        next_bindings = semantic_result.next_bindings
        self.validate_blueprint_agents(
            outcome_blueprint,
            domain=workflow.domain or task.domain,
            scope=scope,
        )
        self._validate_bindings(next_plan, outcome_blueprint, next_bindings)

        new_run_id = self.identity_lifecycle.new_run_id(task.mission_id)
        new_payload = run.model_dump(by_alias=True, mode="json")
        now = utc_now().isoformat()
        new_payload.update({
            "runId": new_run_id,
            "status": WorkflowStatus.PENDING.value,
            "lifecyclePhase": WorkflowProgressPhase.UNDERSTANDING.value,
            "lifecycleMessage": self.replacement_lifecycle_message,
            "startedAt": None,
            "currentStepId": None,
            "output": {},
            "steps": [],
            "checkpoints": [],
            "trace": [],
            "error": None,
            "recoveryCount": 0,
            "idempotencyKey": None,
            "idempotencyFingerprint": None,
            "completedStepIds": [],
            "activeStepIds": [],
            "provenance": None,
            "executionState": self._fresh_replacement_execution_state(run),
            "runtimeRevision": 0,
            "acgBlueprint": outcome_blueprint.model_dump(by_alias=True, mode="json"),
            "createdAt": now,
            "updatedAt": now,
        })
        replacement = RuntimeRunRecord.model_validate(new_payload)
        self.sync_run_steps(replacement, outcome_blueprint)
        compiled_package = ACGGraphCompiler().compile_package(
            outcome_blueprint,
            run_id=replacement.run_id,
        )
        return PreparedSemanticRevision(
            request=request,
            request_checksum=request_checksum,
            source_run=run,
            replacement_run=replacement,
            task=task,
            workflow=workflow,
            scope=scope,
            blueprint=outcome_blueprint,
            next_plan=next_plan,
            next_bindings=next_bindings,
            compiled_package=compiled_package,
            topology_audits=tuple(topology_audits),
        )

    def commit(self, prepared: PreparedSemanticRevision) -> GraphPatchResult:
        """Persist patch artifact, lineage, replacement Run, and source supersession."""

        request = prepared.request
        run = prepared.source_run
        new_run = prepared.replacement_run
        blueprint = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
        outcome_blueprint = prepared.blueprint
        next_plan = prepared.next_plan
        next_bindings = prepared.next_bindings
        compiled_package = prepared.compiled_package

        graph_patch = derive_graph_patch(
            blueprint,
            outcome_blueprint,
            patch_id=request.patch_id,
            reason=request.reason,
        )
        patch_checksum = graph_patch.checksum()
        patch_uri = self.execution_value_store.put_graph_patch(
            run_id=new_run.run_id,
            payload=graph_patch.model_dump(by_alias=True, mode="json"),
        )
        patch_ref = GraphPatchRef(
            patchId=request.patch_id,
            graph=GraphRef(
                graphId=outcome_blueprint.graph_id,
                version=str(outcome_blueprint.version),
            ),
            uri=patch_uri,
            checksum=patch_checksum,
        )
        applied_metadata = list(
            outcome_blueprint.metadata.get("appliedGraphPatches") or []
        )
        patch_entry = {
            "patchId": request.patch_id,
            "idempotencyKey": request.idempotency_key,
            "requestChecksum": prepared.request_checksum,
            "checksum": patch_checksum,
            "baseGraphVersion": request.base_graph_version,
            "graphVersion": outcome_blueprint.version,
            "reason": request.reason,
            "patchRef": patch_uri,
            "sourceRunId": run.run_id,
            "newRunId": new_run.run_id,
        }
        existing_entry = next(
            (
                index for index, entry in enumerate(applied_metadata)
                if isinstance(entry, dict) and entry.get("patchId") == request.patch_id
            ),
            None,
        )
        if existing_entry is not None:
            applied_metadata[existing_entry] = patch_entry
        else:
            applied_metadata.append(patch_entry)
        outcome_blueprint.metadata["appliedGraphPatches"] = applied_metadata
        new_run.acg_blueprint = outcome_blueprint.model_dump(by_alias=True, mode="json")
        new_run.execution_state.update({
            "workflowVersion": prepared.workflow.version,
            "graphId": outcome_blueprint.graph_id,
            "sourceBlueprintVersion": outcome_blueprint.version,
            "graphVersion": outcome_blueprint.version,
            "graphDiff": graph_patch.model_dump(by_alias=True, mode="json"),
            "taskPlanVersion": next_plan.plan_version,
            "taskPlan": next_plan.model_dump(by_alias=True, mode="json"),
            "taskBindings": [
                item.model_dump(by_alias=True, mode="json")
                for item in next_bindings
            ],
            "parentRunId": run.run_id,
            "supersedesRunId": run.run_id,
            "sourcePatchId": request.patch_id,
            **(
                {"topologyAudit": prepared.topology_audits[-1]}
                if prepared.topology_audits else {}
            ),
            "graphPatchRefs": [patch_uri],
            "compiledACGPackage": compiled_package.model_dump(
                by_alias=True, mode="json"
            ),
            "compiledPackageId": compiled_package.package_id,
            "compiledPackageChecksum": compiled_package.checksum,
            "compiledPackageVersion": compiled_package.package_version,
            "compiledPackageBlueprintHash": compiled_package.blueprint_hash,
        })
        run.status = WorkflowStatus.SUPERSEDED
        run.execution_state["supersededByRunId"] = new_run.run_id
        run_graph = deepcopy(run.acg_blueprint or {})
        run_graph["metadata"] = deepcopy(run_graph.get("metadata") or {})
        run_graph["metadata"]["appliedGraphPatches"] = applied_metadata
        run.acg_blueprint = run_graph
        run.updated_at = utc_now()
        self.trace_store.append(
            run,
            TraceEventType.GRAPH_PATCH_APPLIED,
            observation="ACG graph patch applied",
            payload={
                "patchId": request.patch_id,
                "patchRef": patch_uri,
                "baseGraphVersion": request.base_graph_version,
                "graphVersion": outcome_blueprint.version,
                "newRunId": new_run.run_id,
            },
        )
        self.workflow_store.save_graph_patch_transition(
            run,
            new_run,
            {
                "eventId": f"graph.patch.prepared:{run.run_id}:{request.patch_id}",
                "eventType": "graph.patch.prepared",
                "aggregateId": run.run_id,
                "payload": {
                    "missionId": prepared.task.mission_id,
                    "oldRunId": run.run_id,
                    "newRunId": new_run.run_id,
                    "workflowId": new_run.workflow_id,
                    "patchId": request.patch_id,
                    "blueprint": outcome_blueprint.model_dump(
                        by_alias=True, mode="json"
                    ),
                    "taskPlan": next_plan.model_dump(by_alias=True, mode="json"),
                    "taskBindings": [
                        item.model_dump(by_alias=True, mode="json")
                        for item in next_bindings
                    ],
                    "executionState": dict(new_run.execution_state),
                },
            },
        )
        return GraphPatchResult(
            applied=True,
            graphVersion=outcome_blueprint.version,
            runId=new_run.run_id,
            patchRef=patch_ref,
        )

    @staticmethod
    def _validate_bindings(
        plan: TaskPlan,
        blueprint: RuntimeBlueprintSpec,
        bindings: tuple[TaskImplementationBinding, ...],
    ) -> None:
        active_step_ids = {
            node.node_id for node in blueprint.step_nodes()
            if str(node.metadata.get("lifecycleStatus", "active")).lower() != "retired"
        }
        if len({item.plan_node_key for item in bindings}) != len(bindings):
            raise ValueError("Graph Patch contains duplicate semantic bindings")
        if len({item.acg_node_id for item in bindings}) != len(bindings):
            raise ValueError("Graph Patch contains duplicate executable bindings")
        if {item.plan_node_key for item in bindings} != {node.key for node in plan.nodes}:
            raise ValueError("Graph Patch bindings must cover the complete revised TaskPlan")
        if {item.acg_node_id for item in bindings} != active_step_ids:
            raise ValueError("Graph Patch bindings must cover every active executable node")
        validate_bound_acg_semantics(plan, blueprint, bindings, require_exact=True)

    @staticmethod
    def _fresh_replacement_execution_state(
        source: RuntimeRunRecord,
    ) -> dict[str, Any]:
        source_state = (
            source.execution_state if isinstance(source.execution_state, dict) else {}
        )
        inherited_planning_context = (
            "pluginScopeResolution",
            "visibleCapabilityCount",
            "scopeExcludedAgentCount",
            "planningDiversity",
            "requestedCapabilityProfile",
            "effectiveCapabilityProfile",
            "capabilityProfileReason",
            "planningSeed",
            "plannerAlgorithmVersion",
            "evolutionPolicyVersion",
            "evolutionPolicy",
        )
        fresh: dict[str, Any] = {"engineMigration": "langgraph_pending"}
        for key in inherited_planning_context:
            if key in source_state:
                fresh[key] = deepcopy(source_state[key])
        return fresh


__all__ = ["PreparedSemanticRevision", "SemanticRevisionService"]
