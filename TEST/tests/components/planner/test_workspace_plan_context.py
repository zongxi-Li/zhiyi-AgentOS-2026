"""Keep active workspace semantics while summarizing settled page history."""
from copy import deepcopy
import json

import pytest

from components.planner.runtime_decision import decide_runtime
from components.planner.workspace_context import planning_task_plan_context
from contracts import stable_checksum
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningObservation, StepObservation


def context(*, phase="formal", pages=4):
    keys = ["workspace_discovery:understand", "workspace_discovery:inspect",
        *(f"{role}:{index}" for index in range(pages) for role in ("read", "review")),
        "parallel:read", "parallel:review", "pending:analyze", "pending:report"]
    nodes = []
    for key in keys:
        discovery = key.startswith("workspace_discovery:")
        role = ("workspace_discovery" if key.endswith(":inspect") else
            "workspace_acquisition" if "read" in key else
            "workspace_review" if "review" in key else
            "final_synthesis" if key == "pending:report" else "analysis")
        nodes.append(PlannedTask(key=key, title=key,
            objective=f"objective:{key}:" + key * 100,
            capabilityRequirements=("artifact_generation" if key == "pending:report" else
                "verification" if "review" in key else "information_extraction",),
            constraints=[{"workspaceReview": {"targets": [{"path": f"{key}/source.py", "operation": "read"}],
                "longContext": f"constraint:{key}:" + key * 100}}],
            acceptanceCriteria=("Preserve cited facts",), logicalRole=role,
            producedArtifacts=("repository_review",) if key == "pending:report" else (),
            metadata={"source": "workspace_discovery" if discovery else "workspace_review",
                "taskType": "workspace_discovery" if discovery else role}))
    chain = keys[:2 + pages * 2]
    links = list(zip(chain, chain[1:]))
    links.extend([("workspace_discovery:inspect", "parallel:read"),
        ("parallel:read", "parallel:review"),
        (chain[-1], "pending:analyze"), ("parallel:review", "pending:analyze"),
        ("pending:analyze", "pending:report")])
    # Real page revisions retain earlier incoming obligations on the final
    # suffix. Those redundant links must not restore every old review body.
    links.extend((f"review:{index}", "pending:analyze") for index in range(pages - 1))
    metadata = {"workspaceScope": {"version": 1, "requirements": [{"kind": "directory", "path": ".",
        "operation": "read", "recursive": True, "excludePaths": [".git"]}],
        "rationale": "Inspect project source", "sourceRefs": ["receipt:configuration"]}}
    if phase is not None:
        metadata["workspaceDiscovery"] = {"version": 1, "phase": phase, "scopeOrigin": "inferred"}
    plan = TaskPlan(missionId="mission_aabbccddeeff", nodes=tuple(nodes),
        relations=tuple(TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")
            for source, target in links), expectedArtifacts=("repository_review",), metadata=metadata)
    observation = RuntimePlanningObservation(missionId=plan.mission_id, runId="run_context", graphId="graph",
        graphVersion=5, planVersion=plan.plan_version, wakeReason="resume", goal="Review source",
        steps=tuple(StepObservation(stepId="step:" + key, taskKey=key,
            status="pending" if key.startswith("pending:") else "completed",
            outputRef=None if key.startswith("pending:") else "output:" + key,
            commitId=None if key.startswith("pending:") else "commit:" + key,
            auditRef=None if key.startswith("pending:") else "audit:" + key,
            auditOutcome=None if key.startswith("pending:") else "allow") for key in keys),
        remainingStepIds=("step:pending:analyze", "step:pending:report"))
    return plan, observation


def test_old_pages_keep_identity_and_refs_without_repeating_targets_or_long_objectives():
    plan, observation = context()
    before_plan, before_observation = deepcopy(plan), deepcopy(observation)
    projected = planning_task_plan_context(plan, observation)
    by_key = {node["key"]: node for node in projected["nodes"]}
    original = {node["key"]: node for node in plan.model_dump(by_alias=True, mode="json")["nodes"]}
    for key in ("read:0", "review:0", "read:1", "review:1", "read:2", "review:2"):
        node = by_key[key]
        assert node["contextDetail"] == "settled_summary"
        assert node["status"] == "completed" and node["outputRef"] == "output:" + key
        assert node["commitId"] == "commit:" + key and node["auditRef"] == "audit:" + key
        assert node["capabilityRequirements"] == original[key]["capabilityRequirements"]
        assert node["logicalRole"] == original[key]["logicalRole"]
        assert "objective" not in node and "constraints" not in node and "workset" not in node
        assert f"objective:{key}:" not in json.dumps(projected)
        assert f"constraint:{key}:" not in json.dumps(projected)
    assert plan == before_plan and observation == before_observation
    assert projected["contextProjection"]["acceptedPlanFingerprint"] == stable_checksum(
        plan.model_dump(by_alias=True, mode="json"))


def test_current_parallel_frontiers_direct_evidence_and_discovery_keep_full_semantics():
    plan, observation = context()
    projected = planning_task_plan_context(plan, observation)
    original = plan.model_dump(by_alias=True, mode="json")
    by_key = {node["key"]: node for node in projected["nodes"]}
    full = {node["key"]: node for node in original["nodes"] if node["key"] in {
        "workspace_discovery:understand", "workspace_discovery:inspect", "read:3", "review:3",
        "parallel:read", "parallel:review", "pending:analyze", "pending:report"}}
    assert all(by_key[key] == node for key, node in full.items())
    assert [node["key"] for node in projected["nodes"]] == [node["key"] for node in original["nodes"]]
    for key in ("relations", "controlPolicies", "expectedArtifacts", "metadata", "missionId", "planVersion"):
        assert projected[key] == original[key]


def test_graph_growth_adds_summaries_without_restoring_the_settled_page_bodies():
    plan, observation = context(pages=120)
    projected = planning_task_plan_context(plan, observation)
    assert len(projected["nodes"]) == len(plan.nodes)
    assert projected["contextProjection"]["fullNodeCount"] == 8
    assert projected["contextProjection"]["summarizedNodeCount"] == 238
    assert all("objective" not in node for node in projected["nodes"]
        if node["key"].startswith(("read:", "review:")) and node["key"] not in {"read:119", "review:119"})


def test_fingerprint_binds_even_historical_semantics_omitted_from_the_model_view():
    plan, observation = context()
    before = planning_task_plan_context(plan, observation)
    changed = plan.model_copy(update={"nodes": tuple(node.model_copy(update={
        "objective": "Different accepted historic objective"}) if node.key == "read:0" else node
        for node in plan.nodes)})
    after = planning_task_plan_context(changed, observation)
    assert after["nodes"] == before["nodes"]
    assert after["contextProjection"]["acceptedPlanFingerprint"] != before["contextProjection"]["acceptedPlanFingerprint"]


@pytest.mark.parametrize("phase", [None, "discovery"])
def test_legacy_and_discovery_plan_context_is_the_exact_original_payload(phase):
    plan, observation = context(phase=phase)
    assert planning_task_plan_context(plan, observation) == plan.model_dump(by_alias=True, mode="json")
    assert "contextProjection" not in planning_task_plan_context(plan, observation)


def test_unknown_failed_skipped_and_still_scheduled_nodes_are_not_hidden_as_settled_history():
    plan, observation = context()
    steps = tuple(step.model_copy(update={"status": "failed"}) if step.task_key == "read:0" else
        step.model_copy(update={"status": "skipped"}) if step.task_key == "review:0" else step
        for step in observation.steps if step.task_key != "read:1")
    observation = observation.model_copy(update={"steps": steps,
        "remaining_step_ids": (*observation.remaining_step_ids, "step:review:1")})
    nodes = {node["key"]: node for node in planning_task_plan_context(plan, observation)["nodes"]}
    assert all("objective" in nodes[key] for key in ("read:0", "read:1", "review:1"))
    assert nodes["review:0"]["status"] == "skipped" and "objective" not in nodes["review:0"]


def test_single_shot_model_uses_the_shared_projected_plan():
    plan, observation = context()
    requests = []

    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            request = json.loads(prompt)
            requests.append(request)
            return {"observationId": request["observationId"], "action": "continue",
                "reason": "Analyze the existing reviewed findings"}

    decision = decide_runtime(observation=observation, task_plan=plan, llm=Model())
    assert decision.action == "continue" and len(requests) == 1
    assert requests[0]["taskPlan"] == planning_task_plan_context(plan, observation)
