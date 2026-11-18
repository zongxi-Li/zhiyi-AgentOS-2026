"""Remaining source coverage becomes additive, receipt-scoped semantic work."""
from copy import deepcopy
import json

import pytest

from components.planner.runtime_decision import decide_runtime
from components.planner.service import apply_task_plan_patch
from components.planner.workspace_review import _targets, workspace_review_decision
from contracts.execution_evidence import WorkspaceObservationRequirement, _progress
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningObservation, StepObservation


def plan_at(version=1):
    keys = ("understand", "scan", "analysis", "check", "final")
    capabilities = ("task_understanding", "information_extraction", "analysis", "verification", "artifact_generation")
    return TaskPlan(missionId="mission_aabbccddeeff", planVersion=version,
        nodes=tuple(PlannedTask(key=key, title=key, objective="Execute " + key,
            capabilityRequirements=(capability,),
            logicalRole="final_synthesis" if key == "final" else "task",
            producedArtifacts=("report",) if key == "final" else ())
            for key, capability in zip(keys, capabilities)),
        relations=tuple(TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")
            for source, target in zip(keys, keys[1:])), expectedArtifacts=("report",))


def coverage(*, count=3, read=0, listing=True):
    entries = [{"name": f"file-{i:04}.py", "type": "file"} for i in range(count)]
    receipts = [("fs.list", ".", {"entries": entries})] if listing else []
    receipts.extend(("fs.read", f"file-{i:04}.py", {"text": "source"}) for i in range(read))
    return _progress((WorkspaceObservationRequirement(kind="directory", recursive=True),), receipts)


def observe(plan, progress=None, completed=("understand", "scan"), **overrides):
    completed = set(completed)
    payload = dict(missionId=plan.mission_id, runId="run_source", graphId="graph", graphVersion=plan.plan_version,
        planVersion=plan.plan_version, wakeReason="resume", goal="Review the source repository",
        workspaceObservations=coverage() if progress is None else progress,
        steps=tuple(StepObservation(stepId="step:" + node.key, taskKey=node.key,
            status="completed" if node.key in completed else "pending",
            outputRef="output:" + node.key if node.key in completed else None,
            auditOutcome="allow" if node.key in completed else None,
            verificationReport="passed" if node.key in completed
                and node.capability_requirements == ("verification",) else None) for node in plan.nodes),
        remainingStepIds=tuple("step:" + node.key for node in plan.nodes if node.key not in completed))
    payload.update(overrides)
    return RuntimePlanningObservation(**payload)


def scope(node):
    return node.constraints[0]["workspaceReview"]


def test_read_pages_alternate_with_directory_discovery_without_starvation():
    progress = ({"missingReads": ["README.md", "src/main.py", "src/test.py"],
        "missingListings": [f".git/objects/{index:02}" for index in range(16)]},)
    assert _targets(progress, 4) == [
        {"operation": "read", "path": "README.md"},
        {"operation": "list", "path": ".git/objects/00"},
        {"operation": "read", "path": "src/main.py"},
        {"operation": "list", "path": ".git/objects/01"},
    ]
    assert _targets(progress, 1) == [{"operation": "read", "path": "README.md"}]


def test_target_queues_deduplicate_and_continue_when_one_queue_is_exhausted():
    progress = ({"missingReads": ["a.py", "a.py"], "missingListings": ["src", "docs"]},
        {"missingReads": ["a.py", "b.py"], "missingListings": ["src", "tests"]})
    assert _targets(progress, 16) == [
        {"operation": "read", "path": "a.py"}, {"operation": "list", "path": "src"},
        {"operation": "read", "path": "b.py"}, {"operation": "list", "path": "docs"},
        {"operation": "list", "path": "tests"},
    ]


def test_excluded_scope_is_preserved_in_new_work_page_without_excluded_targets():
    requirement = WorkspaceObservationRequirement(kind="directory", recursive=True, excludePaths=[".git"])
    progress = _progress((requirement,), (("fs.list", ".", {"entries": [
        {"name": ".git", "type": "directory"}, {"name": "src", "type": "directory"},
        {"name": "README.md", "type": "file"}]}),))
    decision = workspace_review_decision(observation=observe(plan_at(), progress), task_plan=plan_at())
    reader = decision.task_plan_patch.add_nodes[0]
    assert scope(reader)["targets"] == [
        {"operation": "read", "path": "README.md"}, {"operation": "list", "path": "src"},
    ]


def test_remaining_read_page_and_review_are_deterministic_semantic_patch():
    plan = plan_at()
    observation = observe(plan, coverage(count=3, read=1))
    before = deepcopy(plan)
    decision = workspace_review_decision(observation=observation, task_plan=plan)
    assert decision.action == "revise" and plan == before
    assert decision == workspace_review_decision(observation=observation, task_plan=plan)
    patch = decision.task_plan_patch
    assert patch.base_plan_version == 1 and patch.plan_version == 2
    assert not patch.retire_keys and not patch.replace_keys and not patch.remove_relations
    reader, reviewer = patch.add_nodes
    assert reader.capability_requirements == ("information_extraction",)
    assert reviewer.capability_requirements == ("verification",)
    assert scope(reader)["targets"] == [
        {"operation": "read", "path": "file-0001.py"}, {"operation": "read", "path": "file-0002.py"}]
    assert "file-0000.py" not in reader.objective
    edges = {(r.source_key, r.target_key) for r in patch.relations}
    assert ("scan", reader.key) in edges and (reader.key, reviewer.key) in edges
    assert (reviewer.key, "analysis") in edges
    applied = apply_task_plan_patch(plan, patch)
    assert applied.expected_artifacts == plan.expected_artifacts
    by_key = {node.key: node for node in applied.nodes}
    assert all(by_key[node.key] == node for node in plan.nodes)
    old_incoming = {r for r in plan.relations if r.target_key in {"understand", "scan"}}
    assert {r for r in applied.relations if r.target_key in {"understand", "scan"}} == old_incoming


def test_supplemental_reader_and_reviewer_inherit_accepted_constraints_without_mutating_prefix():
    plan = plan_at()
    mission_constraint = {"type": "mission_constraint", "requirement": "Review the selected source",
        "scope": {"paths": ["src", "tests"]}}
    human_review = {"type": "user_human_review", "required": True,
        "review": {"reasons": ["Caller requested review before delivery"]}}
    local_constraint = {"type": "analysis_format", "sections": ["Findings", "Evidence"]}
    plan = plan.model_copy(update={"nodes": tuple(node.model_copy(update={"constraints":
        [mission_constraint] if node.key == "understand" else
        [human_review] if node.key == "scan" else
        [local_constraint] if node.key == "analysis" else []}) for node in plan.nodes)})
    before = deepcopy(plan)

    decision = workspace_review_decision(observation=observe(plan), task_plan=plan)

    assert decision.action == "revise" and plan == before
    reader, reviewer = decision.task_plan_patch.add_nodes
    inherited = []
    for node in (reader, reviewer):
        reserved = {item["type"]: item for item in node.constraints if "type" in item}
        assert reserved == {"mission_constraint": mission_constraint, "user_human_review": human_review}
        assert scope(node)["targets"]
        assert reserved["mission_constraint"] is not mission_constraint
        assert reserved["mission_constraint"]["scope"]["paths"] is not mission_constraint["scope"]["paths"]
        assert reserved["user_human_review"]["review"]["reasons"] is not human_review["review"]["reasons"]
        inherited.append(reserved)
    applied = apply_task_plan_patch(plan, decision.task_plan_patch)
    by_key = {node.key: node for node in applied.nodes}
    assert all(by_key[node.key] == node for node in before.nodes)
    assert plan == before

    inherited[0]["mission_constraint"]["scope"]["paths"].append("reader-only mutation")
    inherited[1]["user_human_review"]["review"]["reasons"].append("reviewer-only mutation")
    assert inherited[1]["mission_constraint"] == mission_constraint
    assert inherited[0]["user_human_review"] == human_review
    assert plan == before


def test_production_llm_path_schedules_verified_gaps_before_requesting_model_decision():
    class NoModelCall:
        def generate_json(self, *args, **kwargs):
            pytest.fail("source coverage is host-owned and must be scheduled before the LLM decision")
    plan = plan_at()
    result = decide_runtime(observation=observe(plan), task_plan=plan, llm=NoModelCall())
    assert result.action == "revise"


def test_formal_rejection_reaches_planner_instead_of_repeating_the_same_deterministic_patch(monkeypatch):
    import components.planner.runtime_decision as module
    plan = plan_at()
    observation = observe(plan).model_copy(update={"planning_commit_rejection": {
        "observationId": "previous", "code": "INVALID_PROPOSAL", "reason": "compiled candidate changes started work"}})
    calls = []
    def model(llm, **kwargs):
        calls.append(kwargs["prompt"])
        return {"observationId": observation.fingerprint(), "action": "wait", "reason": "Request the missing source input"}
    monkeypatch.setattr(module, "call_planning_model", model)
    result = decide_runtime(observation=observation, task_plan=plan, llm=object())
    assert result.action == "wait" and len(calls) == 1
    assert '"planningCommitRejection"' in calls[0] and "compiled candidate changes started work" in calls[0]


def _fallback_case(kind):
    plan = plan_at()
    if kind == "no_progress":
        patch = workspace_review_decision(observation=observe(plan), task_plan=plan).task_plan_patch
        plan = apply_task_plan_patch(plan, patch)
        observation = observe(plan, completed=("understand", "scan", *(node.key for node in patch.add_nodes)))
    elif kind == "unresolved_scope":
        progress = _progress((WorkspaceObservationRequirement(kind="directory", recursive=True),),
            [("fs.list", ".", {"entries": [{"name": "outside", "type": "symlink"}]})])
        observation = observe(plan, progress)
    else:
        observation = observe(plan, completed={node.key for node in plan.nodes},
            completionBlockers=("workspace_observation_incomplete:0",))
    return plan, observation


@pytest.mark.parametrize("kind", ["no_progress", "unresolved_scope", "final_committed"])
def test_workspace_fallback_reaches_model_with_verified_facts_and_can_revise(kind):
    plan, observation = _fallback_case(kind)
    expected = workspace_review_decision(observation=observation, task_plan=plan)
    requests = []

    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            requests.append(json.loads(prompt))
            return {"observationId": observation.fingerprint(), "action": "revise",
                "reason": "Add targeted source inspection before completing the outstanding scope",
                "taskPlanPatch": {"missionId": plan.mission_id, "basePlanVersion": plan.plan_version,
                    "planVersion": plan.plan_version + 1, "addNodes": [{"key": "targeted_inspection",
                        "title": "Inspect unresolved source", "objective": "Resolve the observed source acquisition gap",
                        "capabilityRequirements": ["information_extraction"]}]}}

    result = decide_runtime(observation=observation, task_plan=plan, llm=Model())

    assert result.action == "revise" and len(requests) == 1
    assert requests[0]["workspaceReviewFallback"] == {"reason": expected.reason}
    assert requests[0]["observation"] == observation.model_dump(by_alias=True, mode="json")
    assert result.task_plan_patch.add_nodes[0].key == "targeted_inspection"


@pytest.mark.parametrize("kind", ["no_progress", "unresolved_scope", "final_committed"])
def test_offline_workspace_fallback_preserves_the_specific_unresolved_reason(kind):
    plan, observation = _fallback_case(kind)
    expected = workspace_review_decision(observation=observation, task_plan=plan)
    assert expected.action == "wait"
    assert decide_runtime(observation=observation, task_plan=plan) == expected


def test_model_cannot_complete_unresolved_workspace_scope_after_fallback():
    from runtime.planning_loop import RuntimePlanningCoordinator

    plan, observation = _fallback_case("final_committed")
    requests = []

    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            requests.append(json.loads(prompt))
            return {"observationId": observation.fingerprint(), "action": "complete", "reason": "The source is done"}

    decision = decide_runtime(observation=observation, task_plan=plan, llm=Model())

    assert requests[0]["workspaceReviewFallback"]["reason"].startswith("WORKSPACE_REVIEW_FINAL_ALREADY_COMMITTED")
    with pytest.raises(ValueError, match="cannot complete unresolved work"):
        RuntimePlanningCoordinator.validate_decision(observation, decision)


def test_existing_original_reader_runs_before_supplemental_page():
    plan = plan_at()
    result = workspace_review_decision(observation=observe(plan, completed=("understand",)), task_plan=plan)
    assert result.action == "continue" and result.task_plan_patch is None


def test_initial_understanding_is_not_rewired_behind_its_dependent_reader():
    plan = plan_at()
    result = workspace_review_decision(observation=observe(plan, completed=()), task_plan=plan)
    assert result.action == "continue"


def test_pending_batch_and_advanced_reader_review_do_not_add_duplicate_work():
    plan = plan_at()
    patch = workspace_review_decision(observation=observe(plan), task_plan=plan).task_plan_patch
    next_plan = apply_task_plan_patch(plan, patch)
    before = observe(next_plan)
    assert workspace_review_decision(observation=before, task_plan=next_plan).action == "continue"
    reader = patch.add_nodes[0]
    advanced = observe(next_plan, coverage(count=3, read=1), completed=("understand", "scan", reader.key))
    result = workspace_review_decision(observation=advanced, task_plan=next_plan)
    assert result.action == "continue" and result.task_plan_patch is None


def test_completed_page_without_new_receipt_coverage_waits_with_explicit_reason():
    plan = plan_at()
    patch = workspace_review_decision(observation=observe(plan), task_plan=plan).task_plan_patch
    next_plan = apply_task_plan_patch(plan, patch)
    result = workspace_review_decision(observation=observe(next_plan,
        completed=("understand", "scan", *(node.key for node in patch.add_nodes))), task_plan=next_plan)
    assert result.action == "wait" and "WORKSPACE_REVIEW_NO_PROGRESS" in result.reason


def test_no_progress_from_invalidated_receipts_reaches_planner_with_causal_recovery_guidance():
    plan, observation = _fallback_case("no_progress")
    progress = deepcopy(observation.workspace_observations)
    progress[0]["coverageInvalidation"] = {"tool": "shell.exec", "receiptRef": "receipt:host",
        "completedAt": "2026-11-17T11:16:20+00:00", "invalidatedReadCount": 2,
        "invalidatedListingCount": 1, "reasonCode": "WORKSPACE_OBSERVATIONS_INVALIDATED"}
    observation = observe(plan, progress,
        completed={step.task_key for step in observation.steps if step.output_ref is not None})
    prompts = []

    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            prompts.append(json.loads(prompt))
            return {"observationId": observation.fingerprint(), "action": "wait",
                "reason": "Resolve the receipt freshness gap"}

    result = decide_runtime(observation=observation, task_plan=plan, llm=Model())
    assert result.action == "wait"
    assert len(prompts) == 1
    reason = prompts[0]["workspaceReviewFallback"]["reason"]
    assert "coverageInvalidation" in reason and "after the latest invalidating operation" in reason
    assert prompts[0]["observation"]["workspaceObservations"] == list(progress)
    assert "do not declare complete" in reason


def test_reader_without_coverage_still_runs_declared_reviewer_before_stopping():
    plan = plan_at()
    patch = workspace_review_decision(observation=observe(plan), task_plan=plan).task_plan_patch
    next_plan = apply_task_plan_patch(plan, patch)
    result = workspace_review_decision(observation=observe(next_plan,
        completed=("understand", "scan", patch.add_nodes[0].key)), task_plan=next_plan)
    assert result.action == "continue" and result.task_plan_patch is None


def test_reviewed_partial_page_adds_only_the_next_remaining_page():
    plan = plan_at()
    patch = workspace_review_decision(observation=observe(plan), task_plan=plan, batch_size=1).task_plan_patch
    plan = apply_task_plan_patch(plan, patch)
    completed = ("understand", "scan", *(node.key for node in patch.add_nodes))
    result = workspace_review_decision(observation=observe(plan, coverage(count=3, read=1), completed=completed),
        task_plan=plan, batch_size=1)
    assert result.action == "revise"
    assert scope(result.task_plan_patch.add_nodes[0])["targets"] == [{"operation": "read", "path": "file-0001.py"}]
    assert {node.key for node in patch.add_nodes}.isdisjoint(node.key for node in result.task_plan_patch.add_nodes)


def test_work_pages_have_no_total_revision_limit_and_never_reread_the_verified_prefix():
    plan, completed = plan_at(), {"understand", "scan"}
    for read in range(40):
        result = workspace_review_decision(observation=observe(plan, coverage(count=41, read=read), completed=completed),
            task_plan=plan, batch_size=1)
        assert result.action == "revise"
        patch = result.task_plan_patch
        assert scope(patch.add_nodes[0])["targets"] == [{"operation": "read", "path": f"file-{read:04}.py"}]
        plan = apply_task_plan_patch(plan, patch)
        completed.update(node.key for node in patch.add_nodes)
    assert plan.plan_version == 41
    assert workspace_review_decision(observation=observe(plan, coverage(count=41, read=41), completed=completed),
        task_plan=plan) is None


def test_directory_discovery_precedes_file_page_without_downgrading_read_requirement():
    plan = plan_at()
    result = workspace_review_decision(observation=observe(plan, coverage(listing=False)), task_plan=plan)
    assert scope(result.task_plan_patch.add_nodes[0])["targets"] == [{"operation": "list", "path": "."}]
    assert "Read means source contents" in result.task_plan_patch.add_nodes[0].objective


def test_unsupported_scope_without_actionable_reads_never_generates_fictitious_exclusions():
    plan = plan_at()
    progress = _progress((WorkspaceObservationRequirement(kind="directory", recursive=True),),
        [("fs.list", ".", {"entries": [{"name": "outside", "type": "symlink"}]})])
    result = workspace_review_decision(observation=observe(plan, progress), task_plan=plan)
    assert result.action == "wait" and "WORKSPACE_SCOPE_UNRESOLVED" in result.reason


def test_completed_final_cannot_be_relabelled_or_counted_as_source_coverage():
    plan = plan_at()
    result = workspace_review_decision(observation=observe(plan, completed={node.key for node in plan.nodes}), task_plan=plan)
    assert result.action == "wait" and "FINAL_ALREADY_COMMITTED" in result.reason
    assert result.task_plan_patch is None


@pytest.mark.parametrize("changes", [
    {"failureType": "policy"}, {"failureType": "storage"}, {"failedStepIds": ("step:scan",)},
    {"completionBlockers": ("review_unresolved:scan",)}, {"wakeReason": "user_input"},
])
def test_scope_patch_does_not_bypass_failure_review_or_new_operator_input(changes):
    plan = plan_at()
    assert workspace_review_decision(observation=observe(plan, **changes), task_plan=plan) is None


def test_stale_observation_does_not_propose_a_patch():
    plan = plan_at()
    with pytest.raises(ValueError, match="current Mission TaskPlan"):
        workspace_review_decision(observation=observe(plan, planVersion=2), task_plan=plan)


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_page_size_must_be_positive_without_limiting_total_pages(batch_size):
    plan = plan_at()
    with pytest.raises(ValueError, match="work page"):
        workspace_review_decision(observation=observe(plan), task_plan=plan, batch_size=batch_size)
