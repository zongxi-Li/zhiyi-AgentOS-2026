"""Workspace planning loads current causal material through immutable references."""
from copy import deepcopy
import json

import pytest

from components.executor.value_store import SQLiteExecutionValueStore
from contracts import stable_checksum
from contracts.runtime_planning import RuntimePlanningObservation
from runtime.workspace_planning_context import (
    load_workspace_discovery_materials, validate_workspace_scope_sources, workspace_discovery_snapshot,
)
from tests.contracts.test_execution_evidence import EvidenceRun


@pytest.fixture
def evidence(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "planning-values.sqlite3")
    try:
        value = EvidenceRun(store)
        value.run.execution_state["taskPlan"] = {"metadata": {
            "workspaceDiscovery": {"version": 1, "phase": "discovery", "scopeOrigin": "inferred"}}}
        yield value
    finally:
        store.close()


def commit(evidence, step_id="inspect", *, role="workspace_discovery", capability="information_extraction", calls=(), **kwargs):
    records = evidence.commit(*calls, step_id=step_id, **kwargs)
    step = evidence.run.get_step(step_id)
    step.logical_role, step.capability = role, capability
    return records


def observe(evidence, snapshot=None):
    return RuntimePlanningObservation(missionId=evidence.run.mission_id, runId=evidence.run.run_id,
        graphId="graph", graphVersion=1, planVersion=1, wakeReason="resume", goal="Review source",
        steps=(), remainingStepIds=(), workspaceDiscovery=(snapshot if snapshot is not None
            else workspace_discovery_snapshot(evidence.run, evidence.store)))


def test_snapshot_contains_references_and_is_stable_while_material_holds_source_bodies(evidence):
    commit(evidence, calls=({"path": "source.py", "text": "source-body-private"},),
        payload={"answer": "discovery-findings-private"})
    before = deepcopy(evidence.run.model_dump())
    first = workspace_discovery_snapshot(evidence.run, evidence.store)
    assert workspace_discovery_snapshot(evidence.run, evidence.store) == first
    observation = observe(evidence, first)
    material = load_workspace_discovery_materials(evidence.store, observation)
    assert material["sources"][0]["findings"] == {"answer": "discovery-findings-private"}
    assert material["observations"][0]["output"]["text"] == "source-body-private"
    assert first["verifiedObservationCount"] == 1
    assert all(text not in observation.model_dump_json() for text in ("source-body-private", "discovery-findings-private"))
    assert evidence.run.model_dump() == before


def test_legacy_and_uncommitted_discovery_do_not_invent_material(evidence):
    assert workspace_discovery_snapshot(evidence.run, evidence.store)["contextRef"] is None
    evidence.run.execution_state.pop("taskPlan")
    assert workspace_discovery_snapshot(evidence.run, evidence.store) is None


@pytest.mark.parametrize("audit", ["deny", "review", None])
def test_discovery_requires_a_committed_allowed_source(evidence, audit):
    commit(evidence, audit=audit, calls=({"path": "source.py"},))
    with pytest.raises(ValueError, match="committed audited source"):
        workspace_discovery_snapshot(evidence.run, evidence.store)


@pytest.mark.parametrize("change", [
    {"record": {"runId": "foreign-run"}}, {"record": {"stepId": "another-step"}},
    {"record": {"commitId": "foreign-commit"}}, {"corrupt_checksum": True},
    {"wal": {"identity": {"runId": "foreign-run"}}}, {"output": {"partial": True}},
])
def test_only_receipts_correlated_with_the_committed_source_enter_material(evidence, change):
    commit(evidence, calls=({"path": "source.py", **change},))
    material = load_workspace_discovery_materials(evidence.store, observe(evidence))
    assert material["observations"] == []


def test_equal_body_from_another_step_cannot_authenticate_a_forged_discovery_receipt_link(evidence):
    donor = commit(evidence, "other", role="task", calls=({"path": "source.py", "text": "same"},))[0]
    commit(evidence, calls=({"path": "source.py", "text": "same", "record": {
        key: donor[key] for key in ("receiptRef", "requestRef", "receiptChecksum")}},))
    material = load_workspace_discovery_materials(evidence.store, observe(evidence))
    assert material["observations"] == []


def test_later_equal_reread_cannot_resurrect_an_invalidated_discovery_receipt(evidence):
    commit(evidence, calls=({"path": "source.py", "text": "same"},))
    commit(evidence, "patch", role="task", calls=({"tool": "fs.patch", "path": "source.py",
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"},))
    commit(evidence, "reread", role="task", calls=({"path": "source.py", "text": "same",
        "started": "2026-11-16T01:00:05+00:00", "ended": "2026-11-16T01:00:06+00:00"},))
    assert load_workspace_discovery_materials(evidence.store, observe(evidence))["observations"] == []


def test_formal_material_contains_discovery_latest_review_and_its_source_page(evidence):
    commit(evidence, calls=({"path": "README.md", "text": "stable discovery source"},))
    for generation in (1, 2):
        commit(evidence, f"read-{generation}", role="workspace_acquisition",
            calls=({"path": f"src/page-{generation}.py", "text": f"page body {generation}"},))
        commit(evidence, f"review-{generation}", role="workspace_review", capability="verification",
            payload={"answer": f"review findings {generation}"})
    commit(evidence, "analysis", role="task", capability="analysis", payload={"answer": "current analysis"})
    chain = ["inspect", "read-1", "review-1", "read-2", "review-2", "analysis"]
    evidence.run.acg_blueprint = {"edges": [{"sourceId": source, "targetId": target}
        for source, target in zip(chain, chain[1:])]}
    evidence.run.execution_state["taskPlan"]["metadata"]["workspaceDiscovery"]["phase"] = "formal"

    material = load_workspace_discovery_materials(evidence.store, observe(evidence))

    assert [source["stepId"] for source in material["sources"]] == ["inspect", "read-2", "review-2", "analysis"]
    assert {item["path"] for item in material["observations"]} == {"README.md", "src/page-2.py"}
    assert "review findings 2" in json.dumps(material) and "review findings 1" not in json.dumps(material)
    assert "page body 1" not in json.dumps(material)


def test_parallel_frontiers_are_preserved_without_a_history_count_limit(evidence):
    commit(evidence)
    evidence.run.execution_state["taskPlan"]["metadata"]["workspaceDiscovery"]["phase"] = "formal"
    for index in range(24):
        commit(evidence, f"branch-{index}", role="workspace_review", capability="verification",
            payload={"answer": f"independent branch {index}"})
    evidence.run.acg_blueprint = {"edges": [{"sourceId": "inspect", "targetId": f"branch-{index}"}
                                          for index in range(24)]}
    material = load_workspace_discovery_materials(evidence.store, observe(evidence))
    assert len(material["sources"]) == 25


@pytest.mark.parametrize("field,value", [("contextChecksum", "0" * 64), ("sourceRefs", []),
    ("contextStepId", "other-step"), ("phase", "formal")])
def test_snapshot_reference_identity_and_checksum_cannot_be_changed(evidence, field, value):
    commit(evidence, calls=({"path": "source.py"},))
    snapshot = workspace_discovery_snapshot(evidence.run, evidence.store)
    snapshot[field] = value
    with pytest.raises(ValueError):
        load_workspace_discovery_materials(evidence.store, observe(evidence, snapshot))


def test_context_ref_is_run_isolated_and_a_replay_loads_exactly_its_original_sources(evidence):
    commit(evidence, payload={"answer": "original"})
    original = observe(evidence)
    first = load_workspace_discovery_materials(evidence.store, original)
    foreign = original.model_copy(update={"run_id": "other-run"})
    with pytest.raises(ValueError):
        load_workspace_discovery_materials(evidence.store, foreign)
    commit(evidence, "later", role="workspace_discovery", payload={"answer": "later source"})
    assert load_workspace_discovery_materials(evidence.store, original) == first
    assert "later source" not in json.dumps(first)
    assert workspace_discovery_snapshot(evidence.run, evidence.store)["contextRef"] != original.workspace_discovery["contextRef"]


@pytest.mark.parametrize("tamper", ["findings", "commitId", "source-provenance", "observation-output", "observation-ref"])
def test_even_rehashed_material_must_match_its_immutable_committed_sources(evidence, tamper):
    commit(evidence, calls=({"path": "source.py", "text": "real source"},), payload={"answer": "real findings"})
    observation = observe(evidence)
    material = deepcopy(load_workspace_discovery_materials(evidence.store, observation))
    if tamper == "findings":
        material["sources"][0]["findings"] = {"answer": "forged"}
    elif tamper == "commitId":
        material["sources"][0]["commitId"] = "forged"
    elif tamper == "source-provenance":
        material["sources"][0].pop("stepId")
    elif tamper == "observation-output":
        material["observations"][0]["output"]["text"] = "forged"
    else:
        material["observations"][0]["receiptRef"] = "tool:unrelated"
    reference = evidence.store.put_tool_value(run_id=evidence.run.run_id, step_id="inspect", key="tampered", payload=material)
    snapshot = {**observation.workspace_discovery, "contextRef": reference, "contextChecksum": stable_checksum(material)}
    with pytest.raises(ValueError):
        load_workspace_discovery_materials(evidence.store, observe(evidence, snapshot))


def test_formal_prefix_reuse_retains_original_receipt_lineage_without_cross_run_fallback(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    commit(evidence, calls=({"path": "source.py", "text": "inherited actual source"},))
    successor = evidence.successor("new-run")
    successor.run.execution_state["taskPlan"] = deepcopy(evidence.run.execution_state["taskPlan"])
    successor.run.get_step("inspect").logical_role = "workspace_discovery"
    material = load_workspace_discovery_materials(successor.store, observe(successor))
    assert material["runId"] == "new-run"
    assert material["observations"][0]["output"]["text"] == "inherited actual source"


def test_preexisting_context_without_new_provenance_fields_keeps_its_frozen_reader(evidence):
    commit(evidence, payload={"answer": "original format"})
    source_ref = evidence.run.execution_state["outputRefs"]["inspect"]
    material = {"version": 1, "runId": evidence.run.run_id,
        "sources": [{"sourceRef": source_ref, "findings": {"answer": "original format"}}], "observations": []}
    reference = evidence.store.put_tool_value(run_id=evidence.run.run_id, step_id="inspect", key="legacy", payload=material)
    snapshot = {"version": 1, "phase": "discovery", "scopeOrigin": "inferred",
        "sourceRefs": [source_ref], "contextRef": reference, "contextChecksum": stable_checksum(material)}
    assert load_workspace_discovery_materials(evidence.store, observe(evidence, snapshot)) == material


def _rejected_proposal(evidence):
    evidence.run.mission_id = "mission_aabbccddeeff"
    observation = observe(evidence)
    feedback = {"observationId": "rejected-observation", "code": "INVALID_PROPOSAL",
                "reason": "candidate changes settled work"}
    proposal = {"version": 1, "observationId": feedback["observationId"],
                "sourceGraphVersion": observation.graph_version,
                "patch": {"missionId": evidence.run.mission_id,
                          "basePlanVersion": observation.plan_version, "planVersion": observation.plan_version + 1,
                          "retireKeys": ["completed-discovery"]},
                "rejection": {key: feedback[key] for key in ("code", "reason")}}
    reference = evidence.store.put_graph_patch(run_id=evidence.run.run_id, payload=proposal)
    return observation.model_copy(update={"planning_commit_rejection": {**feedback, "proposalRef": reference}}), proposal


def test_rejected_candidate_is_resolved_for_correction_without_becoming_read_evidence(evidence):
    from components.planner.workspace_discovery import workspace_planning_material

    commit(evidence, calls=({"path": "source.py", "text": "verified source"},))
    observation, proposal = _rejected_proposal(evidence)
    material = load_workspace_discovery_materials(evidence.store, observation)
    delivered = workspace_planning_material(material)
    assert material["rejectedProposal"] == proposal
    assert delivered["rejectedProposal"]["trustClass"] == "agent_generated"
    assert delivered["observations"]["trustClass"] == "verified_evidence"
    assert material["observations"][0]["output"]["text"] == "verified source"
    assert "completed-discovery" not in observation.model_dump_json()
    # Rejection bodies stay in the existing value store and remain replayable.
    assert load_workspace_discovery_materials(evidence.store, observation) == material


@pytest.mark.parametrize("defect", ["run", "observation", "graph", "plan", "mission", "reason"])
def test_rejected_candidate_cannot_be_mixed_with_other_planning_boundaries(evidence, defect):
    commit(evidence)
    observation, proposal = _rejected_proposal(evidence)
    feedback = dict(observation.planning_commit_rejection)
    if defect == "run":
        owner = "foreign-run"
    else:
        owner = evidence.run.run_id
        if defect == "observation":
            proposal["observationId"] = "other-observation"
        elif defect == "graph":
            proposal["sourceGraphVersion"] += 1
        elif defect == "plan":
            proposal["patch"]["basePlanVersion"] += 1
            proposal["patch"]["planVersion"] += 1
        elif defect == "mission":
            proposal["patch"]["missionId"] = "mission_ffffffffffff"
        else:
            proposal["rejection"]["reason"] = "unrelated rejection"
    feedback["proposalRef"] = evidence.store.put_graph_patch(run_id=owner, payload=proposal)
    with pytest.raises(ValueError):
        load_workspace_discovery_materials(evidence.store,
            observation.model_copy(update={"planning_commit_rejection": feedback}))


def test_legacy_rejection_checksum_preserves_context_without_inventing_a_candidate(evidence):
    commit(evidence)
    original = observe(evidence)
    material = load_workspace_discovery_materials(evidence.store, original)
    legacy = original.model_copy(update={"planning_commit_rejection": {
        "observationId": "old-observation", "code": "INVALID_PROPOSAL", "reason": "invalid candidate",
        "proposalRef": "a" * 64}})
    assert load_workspace_discovery_materials(evidence.store, legacy) == material


def test_scope_revision_can_cite_a_real_committed_review_alongside_other_caller_references(evidence):
    commit(evidence, "review", role="workspace_review", capability="verification", payload={"answer": "findings"})
    source = evidence.run.execution_state["outputRefs"]["review"]
    policy = {"sourceRefs": ["input:caller-goal", source]}
    before = deepcopy((evidence.run.model_dump(), evidence.store.list_node_commits(run_id=evidence.run.run_id)))
    assert validate_workspace_scope_sources(evidence.run, evidence.store, policy) is None
    assert before == (evidence.run.model_dump(), evidence.store.list_node_commits(run_id=evidence.run.run_id))


def test_scope_revision_can_cite_an_exact_current_complete_read_receipt(evidence):
    receipt = commit(evidence, calls=({"path": "source.py"},))[0]["receiptRef"]
    assert validate_workspace_scope_sources(evidence.run, evidence.store, {"sourceRefs": [receipt]}) is None


@pytest.mark.parametrize("refs", [None, [], "output:guessed", ["output:guessed"], [None]])
def test_scope_revision_cannot_ground_itself_in_invented_references(evidence, refs):
    commit(evidence)
    with pytest.raises(ValueError, match="at least one current committed source"):
        validate_workspace_scope_sources(evidence.run, evidence.store, {"sourceRefs": refs})


@pytest.mark.parametrize("change", [{"audit": "deny"}, {"current": False}, {"completed": False}])
def test_scope_revision_needs_current_completed_audited_output(evidence, change):
    commit(evidence, **change)
    source = next(item["outputRef"] for item in evidence.store.list_node_commits(run_id=evidence.run.run_id))
    with pytest.raises(ValueError):
        validate_workspace_scope_sources(evidence.run, evidence.store, {"sourceRefs": [source]})


@pytest.mark.parametrize("change", [{"output": {"partial": True}}, {"corrupt_checksum": True},
    {"record": {"runId": "foreign-run"}}])
def test_scope_revision_cannot_cite_incomplete_or_uncorrelated_read_receipts(evidence, change):
    receipt = commit(evidence, calls=({"path": "source.py", **change},))[0]["receiptRef"]
    with pytest.raises(ValueError, match="at least one current committed source"):
        validate_workspace_scope_sources(evidence.run, evidence.store, {"sourceRefs": [receipt]})


def test_scope_revision_rejects_stale_receipt_even_when_a_new_read_has_identical_body(evidence):
    old = commit(evidence, calls=({"path": "source.py", "text": "same"},))[0]["receiptRef"]
    commit(evidence, "write", role="task", calls=({"tool": "fs.patch", "path": "source.py",
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"},))
    current = commit(evidence, "new-read", role="task", calls=({"path": "source.py", "text": "same",
        "started": "2026-11-16T01:00:05+00:00", "ended": "2026-11-16T01:00:06+00:00"},))[0]["receiptRef"]
    with pytest.raises(ValueError, match="at least one current committed source"):
        validate_workspace_scope_sources(evidence.run, evidence.store, {"sourceRefs": [old]})
    validate_workspace_scope_sources(evidence.run, evidence.store, {"sourceRefs": [current]})


def test_scope_sources_allow_only_proven_cross_run_reuse_lineage(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    receipt = commit(evidence, calls=({"path": "source.py"},))[0]["receiptRef"]
    unrelated = EvidenceRun(evidence.store, "unrelated-run")
    with pytest.raises(ValueError, match="at least one current committed source"):
        validate_workspace_scope_sources(unrelated.run, unrelated.store, {"sourceRefs": [receipt]})
    successor = evidence.successor("proven-copy")
    validate_workspace_scope_sources(successor.run, successor.store, {"sourceRefs": [receipt]})
