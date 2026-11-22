"""Workspace scope revisions remain grounded and preserve caller obligations."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from contracts.workspace_planning import validate_workspace_plan_revision


FULL = {"path": ".", "kind": "directory", "operation": "read", "recursive": True}


def scope(requirements=None, **overrides):
    return {"version": 1, "requirements": [FULL] if requirements is None else requirements,
        "rationale": "Committed discovery identified the relevant source scope",
        "sourceRefs": ["output:discovery"], **overrides}


def plan(*, phase="discovery", origin="inferred", policy=None, requested=None):
    metadata = {"workspaceDiscovery": {"version": 1, "phase": phase, "scopeOrigin": origin}}
    if policy is not None:
        metadata["workspaceScope"] = policy
    return SimpleNamespace(metadata=metadata, nodes=(SimpleNamespace(constraints=[{
        "workspaceDiscovery": {"requestedObservations": [FULL] if requested is None else requested}
    }]),))


def formal_metadata(current, policy=None):
    return {**deepcopy(current.metadata), "workspaceDiscovery": {
        **current.metadata["workspaceDiscovery"], "phase": "formal"},
        "workspaceScope": scope() if policy is None else policy}


def test_grounded_discovery_can_become_formal_without_mutating_the_plan():
    current = plan()
    metadata = formal_metadata(current, scope([{**FULL, "excludePaths": [".git", "build"]}]))
    before = deepcopy((current, metadata))
    assert validate_workspace_plan_revision(current, metadata) is None
    assert current == before[0] and metadata == before[1]


@pytest.mark.parametrize("policy", [None, {}, {"version": 2}, scope([]),
    scope([{**FULL, "excludePaths": ["."]}]), scope([{**FULL, "path": "../outside"}]),
    scope(rationale=""), scope(rationale=" \t"), scope(sourceRefs=[]), scope(sourceRefs="output:discovery"),
    scope(sourceRefs=[None]), scope(sourceRefs=[" "]), scope(sourceRefs=["output:one\noutput:two"])])
def test_formal_transition_requires_valid_scope_rationale_and_traceable_sources(policy):
    current = plan()
    metadata = formal_metadata(current)
    metadata["workspaceScope"] = policy
    with pytest.raises(ValueError):
        validate_workspace_plan_revision(current, metadata)


@pytest.mark.parametrize("stage", [None, {}, {"version": 2, "phase": "formal", "scopeOrigin": "inferred"},
    {"version": True, "phase": "formal", "scopeOrigin": "inferred"},
    {"version": 1, "phase": "unknown", "scopeOrigin": "inferred"},
    {"version": 1, "phase": "formal", "scopeOrigin": "explicit"}])
def test_revision_cannot_remove_downgrade_or_change_discovery_origin(stage):
    current = plan()
    metadata = formal_metadata(current)
    metadata["workspaceDiscovery"] = stage
    with pytest.raises(ValueError):
        validate_workspace_plan_revision(current, metadata)


def test_formal_plan_cannot_return_to_discovery():
    current = plan(phase="formal", policy=scope())
    metadata = deepcopy(current.metadata)
    metadata["workspaceDiscovery"]["phase"] = "discovery"
    with pytest.raises(ValueError, match="return to discovery"):
        validate_workspace_plan_revision(current, metadata)


def test_formal_inferred_scope_can_evolve_without_any_revision_count_limit():
    current = plan(phase="formal", policy=scope())
    for index in range(40):
        metadata = formal_metadata(current, scope([{**FULL, "excludePaths": [f"generated/{index}"]}],
            sourceRefs=[f"output:review-{index}"]))
        validate_workspace_plan_revision(current, metadata)
        current.metadata = metadata


def test_unrelated_formal_revision_does_not_revalidate_or_rewrite_historical_scope():
    current = plan(phase="formal", policy={"version": 1, "requirements": [FULL]})
    metadata = {**deepcopy(current.metadata), "rationale": "Add the next analysis node"}
    assert validate_workspace_plan_revision(current, metadata) is None


@pytest.mark.parametrize("metadata", [{}, {"workspaceScope": {}}])
def test_historical_plans_receive_no_new_workspace_revision_gate(metadata):
    assert validate_workspace_plan_revision(SimpleNamespace(metadata={}, nodes=()), metadata) is None


def test_historical_plan_cannot_bypass_discovery_by_adding_a_formal_protocol_marker():
    with pytest.raises(ValueError, match="initial plan"):
        validate_workspace_plan_revision(SimpleNamespace(metadata={}, nodes=()), {
            "workspaceDiscovery": {"version": 1, "phase": "formal", "scopeOrigin": "inferred"},
            "workspaceScope": scope([{**FULL, "excludePaths": [".git"]}]),
        })


@pytest.mark.parametrize("requirements", [
    [{**FULL, "path": "src"}], [{**FULL, "excludePaths": [".git"]}],
    [{**FULL, "operation": "list"}], [{**FULL, "recursive": False}],
])
def test_explicit_discovery_scope_cannot_be_reduced_during_formalization(requirements):
    current = plan(origin="explicit")
    with pytest.raises(ValueError, match="cannot reduce explicit"):
        validate_workspace_plan_revision(current, formal_metadata(current, scope(requirements)))


@pytest.mark.parametrize("required,expanded", [
    ({"path": "src/main.py", "kind": "file"}, FULL),
    ({**FULL, "path": "src", "excludePaths": ["src/generated"]}, FULL),
    ({**FULL, "path": "src", "operation": "list", "recursive": False}, FULL),
    ({**FULL, "path": "src"}, {**FULL, "excludePaths": [".git"]}),
])
def test_explicit_requirements_can_expand_without_byte_identical_scope(required, expanded):
    current = plan(origin="explicit", requested=[required])
    assert validate_workspace_plan_revision(current, formal_metadata(current, scope([expanded]))) is None


def test_formal_explicit_scope_retains_every_independent_file_obligation():
    current = plan(phase="formal", origin="explicit", policy=scope([
        {**FULL, "excludePaths": ["secret.txt"]}, {"path": "secret.txt", "kind": "file"}]))
    with pytest.raises(ValueError, match="cannot reduce explicit"):
        validate_workspace_plan_revision(current, formal_metadata(current,
            scope([{**FULL, "excludePaths": ["secret.txt"]}])))


def test_a_preliminary_scope_cannot_replace_the_original_explicit_discovery_contract():
    narrow = {**FULL, "path": "src"}
    current = plan(origin="explicit", policy=scope([narrow]))
    with pytest.raises(ValueError, match="cannot reduce explicit"):
        validate_workspace_plan_revision(current, formal_metadata(current, scope([narrow])))


def test_existing_exclusions_allow_subprefixes_but_not_a_larger_excluded_tree():
    required = {**FULL, "path": "src", "excludePaths": ["src/generated/cache"]}
    current = plan(phase="formal", origin="explicit", policy=scope([required]), requested=[required])
    assert validate_workspace_plan_revision(current, formal_metadata(current,
        scope([{**FULL, "path": "src", "excludePaths": ["src/generated/cache/deep"]}]))) is None
    with pytest.raises(ValueError, match="cannot reduce explicit"):
        validate_workspace_plan_revision(current, formal_metadata(current,
            scope([{**FULL, "path": "src", "excludePaths": ["src/generated"]}])))
