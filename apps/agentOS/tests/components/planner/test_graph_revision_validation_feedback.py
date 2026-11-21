"""Graph derivation returns actionable rules without exposing candidate bodies."""

import pytest

from contracts.planning_commit import PlanningCommitRejectionCode as Code
from support.acg.schema import ACGValidationError, ControlNode
from support.acg.validation import validate_blueprint
from test_graph_revision_commit import accepted_source
from test_horizon import ready_boundary, runtime_boundary
from test_planning_commit_runtime import dump_databases


@pytest.mark.parametrize("failure,rule", [
    ("missing", "input_source_missing"),
    ("control", "input_source_not_step"),
    ("unreachable", "input_dependency_missing"),
])
def test_graph_derivation_preserves_input_rule_and_location_without_values(
    ready_boundary, monkeypatch, failure, rule,
):
    from runtime import graph_revision

    runtime, store, ledger, run_id, source, agent = accepted_source(ready_boundary)
    before = dump_databases(store)

    def invalid_lowering(self, *, blueprint, **kwargs):
        consumer = blueprint.step_nodes()[0]
        consumer.input_spec = {"from": {"CANDIDATE_SOURCE_SECRET": ["PRIVATE_FIELD"]}}
        if failure == "control":
            blueprint.nodes.append(ControlNode(nodeId="CANDIDATE_SOURCE_SECRET", controlType="parallel"))
        elif failure == "unreachable":
            blueprint.nodes.append(consumer.model_copy(update={
                "node_id": "CANDIDATE_SOURCE_SECRET", "input_spec": {},
            }, deep=True))
            blueprint.resource_plan = blueprint.resource_plan.model_copy(update={
                "bindings": (*blueprint.resource_plan.bindings,
                    blueprint.resource_plan.bindings[0].model_copy(update={
                        "step_id": "CANDIDATE_SOURCE_SECRET",
                    })),
            })
        validate_blueprint(blueprint)
        pytest.fail("Invalid input binding was accepted")

    monkeypatch.setattr(graph_revision.SemanticGraphPatchService, "apply", invalid_lowering)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="invalid-input")

    assert result.status == "REJECTED" and result.code == Code.INVALID_PROPOSAL
    assert f"nodes.0.inputSpec.from:{rule}" in result.reason
    assert "CANDIDATE_SOURCE_SECRET" not in result.reason and "PRIVATE_FIELD" not in result.reason
    assert ledger.graph_revision_for(source) is None
    assert dump_databases(store) == before and not agent.calls


@pytest.mark.parametrize("error", [
    ValueError("CANDIDATE_BODY_SECRET"),
    KeyError("CANDIDATE_BODY_SECRET"),
    TypeError("CANDIDATE_BODY_SECRET"),
    ACGValidationError("CANDIDATE_BODY_SECRET"),
])
def test_unstructured_derivation_errors_remain_redacted(ready_boundary, monkeypatch, error):
    from runtime import graph_revision

    runtime, _, ledger, run_id, source, _ = accepted_source(ready_boundary)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(graph_revision.SemanticGraphPatchService, "apply", fail)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="unstructured")

    assert result.code == Code.INVALID_PROPOSAL
    assert "unclassified_validation_error" in result.reason
    assert "CANDIDATE_BODY_SECRET" not in result.reason
    assert ledger.graph_revision_for(source) is None
