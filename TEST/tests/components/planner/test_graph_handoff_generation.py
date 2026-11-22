"""Graph handoff preserves real receipts from inherited execution generations."""
import asyncio

import pytest

from contracts.planning import PlannedTask, TaskPlanPatch, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import WorkflowStatus
from TEST.tests.components.planner.test_execution_permit import ready_handoff as ready_handoff


def next_activation(ready_handoff, *, advance_identity_allocation=False, before_execute=None, materialize_only=False):
    rt, workflow, agent, run_id, _, ledger, staged, permits, handoff_id = ready_handoff
    if advance_identity_allocation:
        from domain.models import AcgBlueprint
        source = workflow.get_run(run_id)
        rt.identity_lifecycle.repositories.blueprints.add(AcgBlueprint(missionId=source.mission_id,
            version=2, graphId="retained-other-graph", graph={"version": 1, "nodes": []}))
    identity_metadata = rt.identity_lifecycle.repositories.runs.get(run_id).metadata.copy()
    issued = rt.issue_execution_permit(handoff_id, idempotency_key="generation-two")
    assert issued.status == "ISSUED", issued
    permit = permits.get_permit(issued.permit_id)
    promoted = workflow.get_run(run_id)
    metadata = rt.identity_lifecycle.repositories.runs.get(run_id).metadata
    identity = rt.identity_lifecycle.repositories.runs.get(run_id)
    blueprint = rt.identity_lifecycle.repositories.blueprints.get(identity.blueprint_id)
    assert identity.graph_version == blueprint.version
    assert blueprint.graph["version"] == promoted.acg_blueprint["version"] == 2
    if advance_identity_allocation:
        assert identity.graph_version == 3
    assert metadata["taskPlanVersion"] == promoted.execution_state["taskPlanVersion"] == 2
    for key in ("compiledPackageId", "compiledPackageChecksum", "compiledPackageVersion", "compiledPackageBlueprintHash"):
        assert metadata[key] == promoted.execution_state[key]
    for key, value in identity_metadata.items():
        if key not in {"taskPlanVersion", "runtimeGraphId", "compiledPackageId", "compiledPackageChecksum", "compiledPackageVersion", "compiledPackageBlueprintHash"}:
            assert metadata[key] == value
    if before_execute is not None:
        before_execute(rt, workflow, agent, run_id, permit)

    class Pause:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if any(step.step_id == "B" and step.status == "completed" for step in observation.steps) else "continue",
                reason="inspect the next completed generation boundary")

    rt.runtime_planning_coordinator.planner_for_run = lambda _: Pause()
    boundary = rt.runtime_planning_coordinator.boundary

    async def observe(run, state, reason):
        return await boundary(run, state, "resume" if "B" in state.completed_step_ids else reason)

    rt.runtime_planning_coordinator.boundary = observe
    result = asyncio.run(rt.execute_prepared_run(run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW, (result.status, result.error)
    assert result.completed_step_ids == ["A", "B"] and agent.calls == ["A", "B"]
    activation_id = activate_next_graph(rt, result, materialize_only=materialize_only)
    return rt, workflow, agent, run_id, activation_id, ledger, staged, permit


def activate_next_graph(rt, run, *, key="generation-three", node="E", predecessor="D", materialize_only=False):
    patch = TaskPlanPatch(missionId=run.mission_id,
        basePlanVersion=run.execution_state["taskPlanVersion"],
        planVersion=run.execution_state["taskPlanVersion"] + 1,
        addNodes=(PlannedTask(key="step:" + node, title=node, objective="Inspect remaining evidence",
            capabilityRequirements=("task_understanding",), sourceRefs=("input:brief",)),),
        relations=(TaskPlanRelation(sourceKey="step:" + predecessor, targetKey="step:" + node, relationType="depends_on"),))
    with rt.run_lock_manager.lock_for(run.run_id):
        source = rt.planning_commit_authority.accept_patch_locked(run.run_id, patch,
            proposal_id=key, idempotency_key=key)
    assert source.status == "ACCEPTED", source
    accepted = rt.accept_graph_revision(run.run_id, source.commit_id, idempotency_key=key + "-graph")
    assert accepted.status == "ACCEPTED", accepted
    materialized = rt.materialize_graph_revision(accepted.commit_id, idempotency_key=key + "-materialize")
    assert materialized.status == "MATERIALIZED_INACTIVE", materialized
    if materialize_only:
        return materialized.materialization_id
    prepared = rt.prepare_graph_activation(materialized.materialization_id, idempotency_key=key + "-activate")
    assert prepared.status == "ACTIVATION_PREPARED", prepared
    assert rt.prepare_graph_activation(materialized.materialization_id,
        idempotency_key=key + "-activate").status == "IDEMPOTENT_REPLAY"
    activated = rt.commit_graph_activation(materialized.materialization_id, idempotency_key=key + "-activate")
    assert activated.status == "ACTIVATED_PAUSED", activated
    assert rt.commit_graph_activation(materialized.materialization_id,
        idempotency_key=key + "-activate").status == "IDEMPOTENT_REPLAY"
    return activated.activation_id


@pytest.mark.parametrize("advance_identity_allocation", [False, True])
def test_handoff_accepts_verified_mixed_generation_prefix_without_reexecution(ready_handoff, monkeypatch, advance_identity_allocation):
    from runtime.orchestration import graph_handoff
    rt, workflow, agent, run_id, activation_id, ledger, staged, permit = next_activation(
        ready_handoff, advance_identity_allocation=advance_identity_allocation)
    before = workflow.get_run(run_id)
    receipts = rt.execution_value_store.list_node_commits(run_id=run_id)
    assert len(receipts) == 2
    assert any(r["commitId"] == f"commit:{run_id}:A:0" for r in receipts)
    assert any(r["commitId"] == f"commit:{run_id}:B:0:generation:{permit.attempt_generation}" for r in receipts)
    calls = []
    settled = graph_handoff.assert_replay_safe_operations

    def verify(services, run, **kwargs):
        calls.append(run.run_id)
        return settled(services, run, **kwargs)

    monkeypatch.setattr(graph_handoff, "assert_replay_safe_operations", verify)
    result = rt.prepare_graph_handoff(activation_id, idempotency_key="mixed-generation-handoff")
    assert result.status == "STATE_PREPARED", result
    record = ledger.get_handoff(result.handoff_id)
    assert record.candidate.state["completedStepIds"] == ["A", "B"]
    assert record.candidate.state["outputRefs"] == before.execution_state["outputRefs"]
    assert record.graph_version == 3 and staged.get(record.candidate.checkpoint_id) == record.candidate
    assert set(record.identity_link.prefix_attempt_ids) == {r["nodeExecution"]["attemptId"] for r in receipts}
    assert calls and set(calls) == {run_id}
    assert workflow.get_run(run_id) == before and agent.calls == ["A", "B"]
    assert rt.execution_value_store.list_node_commits(run_id=run_id) == receipts
    assert rt.prepare_graph_handoff(activation_id, idempotency_key="mixed-generation-handoff").status == "IDEMPOTENT_REPLAY"
    next_permit = rt.issue_execution_permit(result.handoff_id, idempotency_key="generation-three-permit")
    assert next_permit.status == "ISSUED", next_permit
    resumed = workflow.get_run(run_id)
    assert resumed.execution_state["executionGeneration"] != permit.attempt_generation
    assert resumed.completed_step_ids == ["A", "B"] and resumed.execution_state["outputRefs"] == before.execution_state["outputRefs"]
    promoted = rt.identity_lifecycle.repositories.runs.get(run_id)
    blueprint = rt.identity_lifecycle.repositories.blueprints.get(promoted.blueprint_id)
    assert promoted.graph_version == blueprint.version
    assert blueprint.graph["version"] == resumed.acg_blueprint["version"] == 3
    assert agent.calls == ["A", "B"] and rt.execution_value_store.list_node_commits(run_id=run_id) == receipts


@pytest.mark.parametrize("authority", ["missing", "wrong-generation"])
def test_handoff_does_not_accept_an_unproved_source_generation(ready_handoff, monkeypatch, authority):
    rt, workflow, agent, run_id, activation_id, ledger, _, _ = next_activation(ready_handoff)
    if authority == "missing":
        rt.execution_permit_authority = None
    else:
        original = rt.execution_permit_authority.store.get_permit
        monkeypatch.setattr(rt.execution_permit_authority.store, "get_permit", lambda key:
            original(key).model_copy(update={"attempt_generation": "foreign-generation"}))
    before = workflow.get_run(run_id)
    result = rt.prepare_graph_handoff(activation_id, idempotency_key="unproved-generation")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(activation_id) is None
    assert workflow.get_run(run_id) == before and agent.calls == ["A", "B"]


@pytest.mark.parametrize("tamper", [None, "compiledPackageChecksum", "compiledPackageBlueprintHash"])
def test_handoff_authenticates_frozen_source_without_recompiling_history(ready_handoff, monkeypatch, tamper):
    from components.executor.compiler import ACGGraphCompiler
    rt, workflow, agent, run_id, activation_id, ledger, _, _ = next_activation(ready_handoff)
    source = next(item for item in ledger.activations_for_run(run_id) if item.candidate_graph_version == 2)
    frozen = ledger.get_materialization(source.materialization_id).package
    compile_package = ACGGraphCompiler.compile_package

    def only_compile_candidate(compiler, blueprint, **kwargs):
        if blueprint.version == 2:
            pytest.fail("historical package was recompiled instead of authenticated")
        return compile_package(compiler, blueprint, **kwargs)

    monkeypatch.setattr(ACGGraphCompiler, "compile_package", only_compile_candidate)
    if tamper is not None:
        repository = rt.identity_lifecycle.repositories.runs
        identity = repository.get(run_id)
        repository.update_blueprint(run_id, identity.blueprint_id, identity.graph_version,
            planning_metadata={tamper: "0" * 64})
    before = workflow.get_run(run_id)

    result = rt.prepare_graph_handoff(activation_id, idempotency_key="frozen-source")

    if tamper is None:
        assert result.status == "STATE_PREPARED", result
        assert ledger.get_handoff(result.handoff_id).identity_link.source_graph.checksum == frozen.checksum
    else:
        assert result.status == "REJECTED", result
        assert result.reason == "source Identity immutable package mismatch"
        assert ledger.handoff_for(activation_id) is None
    assert workflow.get_run(run_id) == before and agent.calls == ["A", "B"]


def test_changed_compiler_cannot_remint_an_already_frozen_candidate(ready_handoff, monkeypatch):
    """A pre-upgrade candidate stays immutable even if it needs explicit migration."""
    from components.executor.compiler import ACGGraphCompiler
    from contracts import stable_checksum
    rt, workflow, agent, run_id, activation_id, ledger, _, _, handoff_id = ready_handoff
    activation = ledger.get_activation(activation_id)
    frozen = ledger.get_materialization(activation.materialization_id)
    compile_package = ACGGraphCompiler.compile_package

    def changed_field_order(compiler, blueprint, **kwargs):
        package = compile_package(compiler, blueprint, **kwargs)
        rules = tuple(reversed(package.communication_manifest.rules))
        changed = package.model_copy(update={"communication_manifest":
            package.communication_manifest.model_copy(update={"rules": rules})})
        body = {field.alias or name: getattr(changed, name)
                for name, field in type(changed).model_fields.items()
                if name not in {"package_id", "checksum"}}
        checksum = stable_checksum(body)
        assert checksum != frozen.package_checksum
        return changed.model_copy(update={"checksum": checksum,
            "package_id": f"acgpkg:{blueprint.graph_id}:{blueprint.version}:{checksum[:16]}"})

    monkeypatch.setattr(ACGGraphCompiler, "compile_package", changed_field_order)
    before = workflow.get_run(run_id)
    handoff = ledger.get_handoff(handoff_id)

    result = rt.prepare_graph_handoff(activation_id, idempotency_key="permit-handoff")

    assert result.status == "REJECTED", result
    assert result.reason == "candidate semantics or current compiler changed"
    assert ledger.get_materialization(activation.materialization_id) == frozen
    assert ledger.get_handoff(handoff_id) == handoff
    assert workflow.get_run(run_id) == before and agent.calls == ["A"]
