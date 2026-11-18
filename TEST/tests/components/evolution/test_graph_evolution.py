"""Offline candidate flow; adapters below are explicit test doubles, not model evaluations."""
import pytest

from components.evolution.graph_service import GraphEvolutionService
from components.evolution.store import InMemoryEvolutionStore
from contracts import stable_checksum
from contracts.evolution import GraphEvolutionProposal, Trajectory, TrajectoryStep


def evidence(index=1, *, error=True):
    return Trajectory(trajectoryId=f"run-{index}", graphVersion=2,
        task={"graphId": "graph-a"},
        steps=[TrajectoryStep(stepId="analyse", actionType="research", feedback={"error": error})],
        outcome={"status": "failed" if error else "completed"})


class Validator:
    def validate(self, proposal, *, trajectories, evaluations):
        assert all(item.graph_version == proposal.base_graph_version for item in trajectories)
        assert all(m["target"] == "analyse" and m["value"] == "verify-evidence" for m in proposal.mutations)


class Evaluator:
    def __init__(self):
        self.quality, self.cost, self.calls = .9, 1.0, 0

    def evaluate(self, proposal):
        from contracts.evolution import GraphEvolutionEvaluation
        self.calls += 1
        return GraphEvolutionEvaluation(proposalId=proposal.proposal_id,
            proposalChecksum=stable_checksum(proposal),
            sampleIds=("held-out-1", "held-out-2"), evaluatorVersion="test-only-v1",
            baselineQuality=.8, candidateQuality=self.quality,
            baselineCost=1.0, candidateCost=self.cost)


class Publisher:
    def __init__(self):
        self.calls = []

    def publish(self, proposal, *, evaluation, approved_by):
        from contracts.evolution import GraphEvolutionPublicationReceipt
        self.calls.append((proposal, evaluation, approved_by))
        return GraphEvolutionPublicationReceipt(proposalId=proposal.proposal_id,
            proposalChecksum=stable_checksum(proposal), graphId=proposal.graph_id,
            graphVersion=proposal.base_graph_version + 1,
            approvedBy=approved_by, publicationRef="test-formal-commit")


@pytest.fixture
def flow():
    from components.evolution.infrastructure.graph_candidates import RegisteredValidatorCandidateGenerator
    from components.evolution.domain.policy import evaluate_trajectory
    generator = RegisteredValidatorCandidateGenerator(validators={"research": "verify-evidence"}, min_failures=2)
    evaluator, publisher = Evaluator(), Publisher()
    store = InMemoryEvolutionStore()
    trajectories = [evidence(i) for i in range(3)]
    evaluations = [evaluate_trajectory(t) for t in trajectories]
    service = GraphEvolutionService(store=store, generator=generator, validator=Validator(),
        evaluator=evaluator, publisher=publisher)
    return service, trajectories, evaluations, evaluator, publisher


def test_repeated_failure_candidate_is_deterministic_and_bound_to_evidence(flow):
    service, trajectories, evaluations, _, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    assert service.propose(list(reversed(trajectories)), list(reversed(evaluations))) == proposal
    assert proposal.mutations == [{"mutationType": "registered_validator_insertion",
                                    "target": "analyse", "value": "verify-evidence"}]
    assert proposal.evidence_trajectory_ids == [t.trajectory_id for t in trajectories]
    assert not publisher.calls


def test_evaluated_candidate_delegates_to_injected_publisher(flow):
    service, trajectories, evaluations, evaluator, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    report = service.evaluate_proposal(proposal)
    receipt = service.apply_approved_proposal(proposal, evaluation=report, approved_by=" reviewer ")
    assert receipt.graph_version == 3
    assert receipt.publication_ref == "test-formal-commit"
    assert publisher.calls[0][2] == "reviewer"
    assert evaluator.calls == 2  # Publishing rechecks the trusted evaluator, not caller-supplied scores.


@pytest.mark.parametrize("quality,cost", [(.7, 1.0), (.9, 1.1)])
def test_quality_regression_or_cost_increase_prevents_publication(flow, quality, cost):
    service, trajectories, evaluations, evaluator, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    evaluator.quality, evaluator.cost = quality, cost
    with pytest.raises(ValueError, match="quality|cost"):
        service.apply_approved_proposal(proposal, approved_by="reviewer")
    assert not publisher.calls


def test_altered_evaluation_cannot_authorize_publication(flow):
    service, trajectories, evaluations, _, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    report = service.evaluate_proposal(proposal)
    with pytest.raises(ValueError, match="evaluation"):
        service.apply_approved_proposal(proposal,
            evaluation=report.model_copy(update={"candidate_quality": 1.0}), approved_by="reviewer")
    assert not publisher.calls


def test_proposal_with_changed_graph_or_unbounded_mutation_is_rejected(flow):
    service, trajectories, evaluations, _, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    for altered in (proposal.model_copy(update={"graph_id": "another"}),
                    proposal.model_copy(update={"base_graph_version": 3}),
                    proposal.model_copy(update={"mutations": [{"code": "arbitrary"}]}),
                    proposal.model_copy(update={"evidence_trajectory_ids": ["run-0", "run-0", "run-0"]})):
        with pytest.raises(ValueError):
            service.validate_proposal(altered)
    assert not publisher.calls


def test_missing_dependencies_never_report_fake_success(flow):
    service, trajectories, evaluations, _, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    with pytest.raises(NotImplementedError):
        GraphEvolutionService().propose_mutation(trajectories[0], evaluations[0])
    service.publisher = None
    with pytest.raises(NotImplementedError):
        service.apply_approved_proposal(proposal, approved_by="reviewer")
    assert not publisher.calls


def test_too_few_distinct_runs_or_mismatched_evaluation_rejected(flow):
    service, trajectories, evaluations, _, _ = flow
    with pytest.raises(ValueError, match="distinct|evidence"):
        service.propose([trajectories[0]] * 3, [evaluations[0]] * 3)
    with pytest.raises(ValueError, match="evaluation"):
        service.propose(trajectories, evaluations[:-1])


def test_successful_runs_do_not_invent_a_failure_candidate(flow):
    from components.evolution.domain.policy import evaluate_trajectory
    service, _, _, _, _ = flow
    trajectories = [evidence(i, error=False) for i in range(3)]
    with pytest.raises(ValueError, match="failure"):
        service.propose(trajectories, [evaluate_trajectory(t) for t in trajectories])


def test_multiple_snapshots_of_one_run_do_not_count_as_distinct_failure_evidence(flow):
    service, trajectories, evaluations, _, _ = flow
    trajectories = [t.model_copy(update={"task": {"graphId": "graph-a", "runId": "same-run"}})
                    for t in trajectories]
    with pytest.raises(ValueError, match="distinct|evidence"):
        service.propose(trajectories, evaluations)


@pytest.mark.parametrize("change", [
    {"proposal_checksum": "0" * 64}, {"sample_ids": ("run-0",)},
    {"sample_ids": ("repeat", "repeat")}, {"candidate_cost": float("nan")},
])
def test_invalid_offline_report_never_reaches_publisher(flow, change):
    service, trajectories, evaluations, evaluator, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    trusted = evaluator.evaluate
    evaluator.evaluate = lambda p: trusted(p).model_copy(update=change)
    with pytest.raises(ValueError):
        service.apply_approved_proposal(proposal, approved_by="reviewer")
    assert not publisher.calls


def test_stale_graph_from_formal_publisher_is_propagated(flow):
    service, trajectories, evaluations, _, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    def stale(*args, **kwargs):
        raise ValueError("formal graph CAS is stale")
    publisher.publish = stale
    with pytest.raises(ValueError, match="stale"):
        service.apply_approved_proposal(proposal, approved_by="reviewer")


def test_offline_samples_cannot_reuse_underlying_run_identity(flow):
    service, trajectories, evaluations, evaluator, publisher = flow
    trajectories = [t.model_copy(update={"task": {"graphId": "graph-a", "runId": f"source-{i}"}})
                    for i, t in enumerate(trajectories)]
    proposal = service.propose(trajectories, evaluations)
    trusted = evaluator.evaluate
    evaluator.evaluate = lambda p: trusted(p).model_copy(update={"sample_ids": ("source-0",)})
    with pytest.raises(ValueError, match="held-out"):
        service.apply_approved_proposal(proposal, approved_by="reviewer")
    assert not publisher.calls


def test_publication_uses_an_input_snapshot_across_adapter_calls(flow):
    service, trajectories, evaluations, evaluator, publisher = flow
    proposal = service.propose(trajectories, evaluations)
    trusted = evaluator.evaluate
    def evaluate(copy):
        proposal.mutations[0]["target"] = "changed-by-caller"
        return trusted(copy)
    evaluator.evaluate = evaluate
    receipt = service.apply_approved_proposal(proposal, approved_by="reviewer")
    assert receipt.graph_version == 3
    assert publisher.calls[0][0].mutations[0]["target"] == "analyse"
