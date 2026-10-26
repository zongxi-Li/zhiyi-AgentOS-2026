"""User policy is accepted semantic evidence and immutable compilation input."""
import pytest

from contracts.planning import TaskPlan, PlannedTask
from runtime.human_review_policy import bind_review_policy, validate_review_policy, review_policy
from test_initial_planning_sources import initial_run, accept
from test_horizon import ready_boundary, runtime_boundary


@pytest.mark.freeze_gate
def test_model_constraints_cannot_cancel_the_explicit_user_policy():
    plan = TaskPlan(missionId='mission_0123456789ab', nodes=(PlannedTask(key='deliver', title='deliver',
        objective='deliver', capabilityRequirements=('artifact_generation',),
        constraints=[{'type': 'user_human_review', 'policyVersion': 'agent-bypass'}]),))
    with pytest.raises(ValueError, match='conflicts'):
        validate_review_policy(plan, 'human_in_loop')
    bound = bind_review_policy(plan, 'human_in_loop')
    validate_review_policy(bound, 'human_in_loop')
    assert bound.nodes[0].constraints == [{'type': 'user_human_review', **review_policy('human_in_loop')}]
    with pytest.raises(ValueError, match='conflicts'):
        validate_review_policy(bound, 'auto')
    with pytest.raises(ValueError, match='unsupported'):
        bind_review_policy(plan, 'unrecognized')


@pytest.mark.freeze_gate
def test_initial_manual_policy_is_frozen_and_mode_drift_is_not_reinterpreted(initial_run):
    runtime, store, _, run, _ = initial_run
    run.review_mode = 'human_in_loop'
    store.save_run(run)
    record = accept(initial_run)
    origin = record.source_provenance
    assert origin.lowering_options['reviewPolicy']['scope'] == 'all-executable-steps'
    from runtime.initial_graph_compilation import compile_initial_content
    content = compile_initial_content(record)
    assert content.blueprint.step_nodes()
    assert all(step.review_required for step in content.blueprint.step_nodes())
    assert content.blueprint.metadata['reviewPolicy'] == origin.lowering_options['reviewPolicy']
    validate_review_policy(record.proposal_payload, 'human_in_loop')
    run = store.get_run(run.run_id)
    run.review_mode = 'auto'
    store.save_run(run)
    assert runtime.planning_commit_authority.validate_initial_sources(record.commit_id) is not None
