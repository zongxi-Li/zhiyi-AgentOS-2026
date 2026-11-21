"""Project frozen graph semantics without overlaying mutable Run preferences."""


def project_frozen_graph_steps(runtime, run, blueprint):
    # The initial compilation recipe uses only the sealed blueprint. Reuse its
    # existing projector while retaining the source steps' execution history.
    view = run.model_copy(deep=True, update={"input": {}, "execution_state": {}})
    runtime._sync_run_steps_to_acg(view, blueprint)
    return view


def restore_revision_source_steps(runtime, source_run, source_blueprint, candidate_blueprint, *, protected_step_ids):
    """Rebuild retired/rewired pending source steps from their frozen graph.

    Activation replaces only the candidate projection. The source view is used
    solely for the accepted provenance and safe-cut verification; completed or
    otherwise evidenced work must retain every byte of its execution history.
    """
    source_nodes = {node.node_id: node for node in source_blueprint.step_nodes()}
    candidate_nodes = {node.node_id: node for node in candidate_blueprint.step_nodes()}
    source_bindings = {binding.step_id: binding for binding in source_blueprint.resource_plan.bindings}
    candidate_bindings = {binding.step_id: binding for binding in candidate_blueprint.resource_plan.bindings}
    rewritten = {node_id for node_id, node in source_nodes.items()
        if node != candidate_nodes.get(node_id) or source_bindings.get(node_id) != candidate_bindings.get(node_id)}
    if rewritten & set(protected_step_ids):
        raise ValueError("historical source reconstruction cannot change protected work")
    if not rewritten:
        return
    current = {step.step_id: step for step in source_run.steps}
    candidate = {step.step_id: step for step in project_frozen_graph_steps(runtime, source_run, candidate_blueprint).steps}
    for node_id in rewritten & current.keys():
        if current[node_id] != candidate.get(node_id):
            raise ValueError("rewritten candidate step differs from its frozen projection")
    frozen = {step.step_id: step for step in project_frozen_graph_steps(runtime, source_run, source_blueprint).steps}
    source_run.steps = [frozen[node_id] if node_id in rewritten else current[node_id] for node_id in source_nodes]


def restore_initial_source_steps(runtime, source_run, blueprint):
    """Reconstruct the formal v1 recipe for validation of historical sources.

    Earlier revision activations reapplied Run reasoning/evolution preferences
    to existing steps. This view is never persisted or executed; the accepted
    source fingerprint must still prove every reconstructed byte.
    """
    if blueprint.version == 1 and blueprint.metadata.get("initialCommitId"):
        view = project_frozen_graph_steps(runtime, source_run, blueprint)
        legacy = source_run.model_copy(deep=True)
        runtime._sync_run_steps_to_acg(legacy, blueprint)
        frozen_inputs = {step.step_id: step.input for step in view.steps}
        legacy_inputs = {step.step_id: step.input for step in legacy.steps}
        for step in source_run.steps:
            if step.step_id in frozen_inputs and step.input == legacy_inputs[step.step_id]:
                # Undo only a recognized legacy preference overlay. Preserve
                # unrelated input/semantic changes for the frozen hash to reject.
                step.input = frozen_inputs[step.step_id]
