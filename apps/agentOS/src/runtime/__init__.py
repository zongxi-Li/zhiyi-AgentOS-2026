"""Stable, lazy runtime API; importing the package does not assemble services."""

from importlib import import_module


_EXPORTS = {'bootstrap': ('runtime.composition.bootstrap', 'bootstrap'),
 'ApplicationSetup': ('runtime.composition.app_setup', 'ApplicationSetup'),
 'ApplicationSetupError': ('runtime.composition.app_setup', 'ApplicationSetupError'),
 'ModelSetup': ('runtime.composition.app_setup', 'ModelSetup'),
 'ExecutionRuntime': ('runtime.workflow_runtime', 'ExecutionRuntime'),
 'build_default_runtime': ('runtime.workflow_runtime', 'build_default_runtime'),
 'AcgIdentityLifecycleService': ('components.mission.identity_lifecycle',
                                 'AcgIdentityLifecycleService'),
 'ExecutionContext': ('contracts.execution_context', 'ExecutionContext'),
 'IdentityProjectionBridge': ('runtime.orchestration.identity_projection',
                              'IdentityProjectionBridge'),
 'IdentityProjectionReconciler': ('runtime.orchestration.reconciliation',
                                  'IdentityProjectionReconciler'),
 'IdentityReconciliationReport': ('runtime.orchestration.reconciliation',
                                  'IdentityReconciliationReport'),
 'IdentityQueryService': ('runtime.projections.queries', 'IdentityQueryService'),
 'PlannerIdentityBridge': ('runtime.orchestration.planner_bridge', 'PlannerIdentityBridge'),
 'MissionWorkspaceProjection': ('runtime.projections.workspace', 'MissionWorkspaceProjection'),
 'MissionWorkspaceProjector': ('runtime.projections.workspace', 'MissionWorkspaceProjector'),
 'WorkspaceDiagnostic': ('runtime.projections.workspace', 'WorkspaceDiagnostic'),
 'WorkspaceEntry': ('runtime.projections.workspace', 'WorkspaceEntry'),
 'WorkspaceEntryKind': ('runtime.projections.workspace', 'WorkspaceEntryKind'),
 'WorkspaceGraphNode': ('runtime.projections.workspace', 'WorkspaceGraphNode'),
 'WorkspaceIdentityQuality': ('runtime.projections.workspace', 'WorkspaceIdentityQuality'),
 'WorkspaceRunSummary': ('runtime.projections.workspace', 'WorkspaceRunSummary'),
 'TaskImplementationBinding': ('contracts.planning', 'TaskImplementationBinding'),
 'TaskPlan': ('contracts.planning', 'TaskPlan'),
 'PlannedTask': ('contracts.planning', 'PlannedTask'),
 'TaskPlanPatch': ('contracts.planning', 'TaskPlanPatch')}


_MODULES = {
    "app_setup": "runtime.composition.app_setup",
    "bootstrap_module": "runtime.composition.bootstrap",
    "context": "runtime.composition.context",
    "dependencies": "runtime.composition.dependencies",
    "ports": "runtime.composition.ports",
    "acg_execution": "runtime.orchestration.acg_execution",
    "binding": "runtime.orchestration.binding",
    "execution_permit": "runtime.orchestration.execution_permit",
    "graph_activation": "runtime.orchestration.graph_activation",
    "graph_handoff": "runtime.orchestration.graph_handoff",
    "graph_materialization": "runtime.orchestration.graph_materialization",
    "graph_revision": "runtime.orchestration.graph_revision",
    "identity_projection": "runtime.orchestration.identity_projection",
    "initial_execution": "runtime.orchestration.initial_execution",
    "initial_planning_sources": "runtime.orchestration.initial_planning_sources",
    "permit_recovery": "runtime.orchestration.permit_recovery",
    "planner_bridge": "runtime.orchestration.planner_bridge",
    "planning_application": "runtime.orchestration.planning_application",
    "planning_commit": "runtime.orchestration.planning_commit",
    "planning_interaction": "runtime.orchestration.planning_interaction",
    "planning_loop": "runtime.orchestration.planning_loop",
    "planning_observation": "runtime.orchestration.planning_observation",
    "planning_operations": "runtime.orchestration.planning_operations",
    "planning_wait": "runtime.orchestration.planning_wait",
    "reconciliation": "runtime.orchestration.reconciliation",
    "review": "runtime.orchestration.review",
    "runtime_recovery": "runtime.orchestration.runtime_recovery",
    "semantic_revision": "runtime.orchestration.semantic_revision",
    "state_persistence": "runtime.orchestration.state_persistence",
    "copilot_projection": "runtime.projections.copilot_projection",
    "queries": "runtime.projections.queries",
    "query_models": "runtime.projections.query_models",
    "resume_projection": "runtime.projections.resume_projection",
    "runtime_display": "runtime.projections.runtime_display",
    "workspace": "runtime.projections.workspace",
    "live_events": "runtime.events.live_events",
    "execution_migration": "runtime.compatibility.execution_migration",
    "human_review_policy": "components.auditor.human_review_policy",
    "semantic_patch": "components.planner.semantic_patch",
    "initial_graph_compilation": "components.planner.initial_graph_compilation",
    "planner_input_adapter": "components.mission.planner_input",
    "runner": "components.mission.identity_lifecycle",
    "model_quota": "components.resource.model_quota",
    "state": "domain.lifecycle",
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attribute = target
        value = getattr(import_module(module_name), attribute)
    else:
        module_name = _MODULES.get(name)
        if module_name is None:
            raise AttributeError(name)
        value = import_module(module_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
