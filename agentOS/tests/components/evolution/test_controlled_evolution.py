"""Controlled policy evolution determinism, CAS and future-run semantics."""

from __future__ import annotations

import pytest

from components.evolution.service import EvolutionService
from components.evolution.store import EvolutionVersionConflict
from contracts.evolution import PolicyMutation, Trajectory, TrajectoryStep


def _trajectory(index: int) -> Trajectory:
    return Trajectory(
        trajectoryId=f"trajectory-{index}",
        task={"domain": "general"},
        steps=[TrajectoryStep(stepId="analyse", actionType="agent", feedback={})],
        outcome={"status": "completed", "quality": 0.8},
    )


def test_same_trajectory_and_set_produce_same_evaluation_and_proposal() -> None:
    service = EvolutionService(proposal_threshold=3)
    trajectories = [_trajectory(3), _trajectory(1), _trajectory(2)]
    mutation = PolicyMutation(
        mutationType="budget_adjustment", target="analysis", value=4096
    )

    assert service.evaluate(trajectories[0]) == service.evaluate(trajectories[0])
    first = service.propose(trajectories, mutation)
    second = service.propose(list(reversed(trajectories)), mutation)

    assert first == second
    assert first is not None and first.status.value == "pending_review"


def test_unapproved_proposal_does_not_change_active_policy_and_approval_uses_cas() -> None:
    service = EvolutionService(proposal_threshold=1)
    proposal = service.propose(
        [_trajectory(1)],
        PolicyMutation(mutationType="skill_preference_adjustment", target="research", value="skill.v2"),
    )
    assert proposal is not None
    assert service.store.active().version == 0

    approved = service.approve(proposal, approved_by="reviewer")
    assert approved.version == 1
    with pytest.raises(ValueError, match="stale"):
        service.approve(proposal, approved_by="reviewer")


def test_rollback_creates_a_new_version_without_rewriting_history() -> None:
    service = EvolutionService(proposal_threshold=1)
    proposal = service.propose(
        [_trajectory(1)],
        PolicyMutation(mutationType="budget_adjustment", target="analysis", value=2048),
    )
    assert proposal is not None
    service.approve(proposal, approved_by="reviewer")

    rollback = service.rollback(0, approved_by="reviewer")

    assert rollback.version == 2
    assert rollback.policy == {}
    assert service.store.get(1).policy != {}
