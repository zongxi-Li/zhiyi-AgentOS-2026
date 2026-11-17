"""Formal compilation and handoff preserve complete accepted graphs at any size."""
import pytest

from contracts.planning import PlannedTask, TaskPlanPatch, TaskPlanRelation
from support.stores.graph_activation_store import SQLiteGraphActivationStore
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from test_graph_handoff import attach as attach_handoff
from test_horizon import ready_boundary as ready_boundary, runtime_boundary as runtime_boundary
from test_planning_commit_runtime import attach as attach_commit


@pytest.fixture(autouse=True)
def documented_contract(monkeypatch):
    import test_htn
    create = test_htn.runtime_at

    def runtime_at(path):
        runtime, workflow, agent = create(path)
        build = runtime._build_acg_blueprint

        def blueprint_with_skill_contract(*args, **kwargs):
            from support.acg.planning import SkillRequirementSpec
            blueprint, plan, bindings = build(*args, **kwargs)
            # Establish a real skill schema before any graph/package is frozen.
            # Its full documentation must survive compilation and later edits.
            schema = SkillRequirementSpec(stepId="A", skillId="documented-review",
                inputSpec={"description": "Authorized schema reference. " + "x" * 4_000_000})
            blueprint.resource_plan = blueprint.resource_plan.model_copy(update={
                "skills": (*blueprint.resource_plan.skills, schema)})
            return blueprint, plan, bindings

        runtime._build_acg_blueprint = blueprint_with_skill_contract
        return runtime, workflow, agent

    monkeypatch.setattr(test_htn, "runtime_at", runtime_at)


def test_large_accepted_package_and_handoff_have_no_total_size_or_step_ceiling(ready_boundary):
    rt, workflow, agent, run_id, state = ready_boundary
    run = workflow.get_run(run_id)
    rt.acg_state_persistence.save_checkpoint(run, state)
    rt.acg_state_persistence.persist(run, state)
    attach_commit(rt, workflow)
    keys = tuple(f"additional:{index:03}" for index in range(257))
    patch = TaskPlanPatch(missionId=run.mission_id,
        basePlanVersion=run.execution_state["taskPlanVersion"],
        planVersion=run.execution_state["taskPlanVersion"] + 1,
        addNodes=tuple(PlannedTask(key=key, title=key, objective="Inspect source evidence.",
            capabilityRequirements=("task_understanding",)) for key in keys),
        relations=tuple(TaskPlanRelation(sourceKey="step:A", targetKey=key, relationType="depends_on") for key in keys))
    with rt.run_lock_manager.lock_for(run_id):
        source = rt.planning_commit_authority.accept_patch_locked(run_id, patch,
            proposal_id="complete-large-candidate", idempotency_key="large-semantic")
    assert source.status == "ACCEPTED", source
    accepted = rt.accept_graph_revision(run_id, source.commit_id, idempotency_key="large-graph")
    assert accepted.status == "ACCEPTED", accepted
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    materials = SQLiteGraphMaterializationStore(workflow.db_path)
    rt.enable_graph_materialization(materials)
    materialized = rt.materialize_graph_revision(accepted.commit_id, idempotency_key="large-materialization")
    assert materialized.status == "MATERIALIZED_INACTIVE", materialized
    record = materials.get_materialization(materialized.materialization_id)
    assert len(record.model_dump_json()) > 4_000_000
    assert len(record.package.nodes) == 258
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    rt.enable_graph_activation(SQLiteGraphActivationStore(workflow.db_path))
    assert rt.prepare_graph_activation(record.materialization_id, idempotency_key="large-activation").status == "ACTIVATION_PREPARED"
    activated = rt.commit_graph_activation(record.materialization_id, idempotency_key="large-activation")
    assert activated.status == "ACTIVATED_PAUSED", activated
    before = workflow.get_run(run_id)
    assert len(before.steps) > 256 and len(before.model_dump_json()) > 2_000_000
    ledger, staged = attach_handoff(rt, workflow)
    handoff = rt.prepare_graph_handoff(activated.activation_id, idempotency_key="large-handoff")
    assert handoff.status == "STATE_PREPARED", handoff
    prepared = ledger.get_handoff(handoff.handoff_id)
    assert staged.get(prepared.candidate.checkpoint_id) == prepared.candidate
    assert prepared.candidate.state["completedStepIds"] == []
    assert prepared.candidate.state["outputRefs"] == {}
    assert workflow.get_run(run_id) == before and not agent.calls
