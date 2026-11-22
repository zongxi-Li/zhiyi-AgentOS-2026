"""Canonical graph revision accepts semantic policy changes without a topology edit."""

import pytest
from pydantic import ValidationError

from contracts.recovery import SemanticPatchRequest


def request(**patch):
    return SemanticPatchRequest(
        patchId="semantic-policy",
        idempotencyKey="semantic-policy:v3",
        runId="run",
        graphId="graph",
        baseGraphVersion=2,
        taskPlanPatch={
            "missionId": "mission_0123456789ab",
            "basePlanVersion": 2,
            "planVersion": 3,
            **patch,
        },
    )


@pytest.mark.parametrize("metadata", [
    {"workspaceScope": {
        "version": 1,
        "requirements": [{"path": ".", "kind": "directory", "operation": "read",
                          "recursive": True, "excludePaths": [".git", ".cache"]}],
        "rationale": "Committed ignore configuration identifies generated files",
        "sourceRefs": ["receipt:ignore", "output:source"],
    }},
    {"workspaceDiscovery": {"version": 1, "phase": "formal", "scopeOrigin": "inferred"}},
])
def test_workspace_policy_can_advance_the_graph_without_replacing_any_node(metadata):
    value = request(metadata=metadata)
    patch = value.task_plan_patch
    assert patch.metadata == metadata
    assert not patch.add_nodes and not patch.retire_keys and not patch.replace_keys
    assert not patch.remove_relations and not patch.relations
    assert SemanticPatchRequest.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("artifacts", [[], ["repository_review"]])
def test_explicit_expected_artifact_revision_is_a_semantic_change(artifacts):
    assert request(expectedArtifacts=artifacts).task_plan_patch.expected_artifacts == tuple(artifacts)


@pytest.mark.parametrize("patch", [
    {},
    {"expectedArtifacts": None},
    {"metadata": {}},
    {"metadata": {"rationale": "Explain the existing plan", "source": "workspace_review"}},
    {"metadata": {"sourceRefs": ["output:existing"]}},
    {"metadata": {"workspaceScope": {}}},
    {"metadata": {"workspaceDiscovery": None}},
    {"metadata": {"unrelated": {"workspaceScope": {"version": 1}}}},
])
def test_empty_or_annotation_only_revision_does_not_create_an_empty_version_loop(patch):
    expected = ("metadata contains non-planning keys"
                if set(patch.get("metadata", {})) & {"sourceRefs", "unrelated"}
                else "requires a semantic TaskPlan change")
    with pytest.raises(ValidationError, match=expected):
        request(**patch)
