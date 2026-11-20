"""Project frozen graph semantics without overlaying mutable Run preferences."""


def project_frozen_graph_steps(runtime, run, blueprint):
    # The initial compilation recipe uses only the sealed blueprint. Reuse its
    # existing projector while retaining the source steps' execution history.
    view = run.model_copy(deep=True, update={"input": {}, "execution_state": {}})
    runtime._sync_run_steps_to_acg(view, blueprint)
    return view


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
