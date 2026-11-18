"""Signed Hands evidence survives local review revisions and reaches delivery."""
# ruff: noqa: F811
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest

from adapters.audited_tool_runtime import ToolAuthorizationError
from adapters.hands_http import receipt_checksum
from components.planner.runtime_decision import decide_runtime
from contracts.execution_evidence import workspace_observation_progress
from contracts.mission_semantic import MissionSemanticRequest
from contracts.planning import PlannedTask, TaskPlanRelation
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from service.agents.base import AgentOutput
from test_workspace_review_execution import (
    configure, hands_stack, initial_run, ready_boundary, runtime_boundary,
)


def _with_delivery_suffix(initial_run, *, with_scan):
    """Prepare an ordinary immutable plan before any supplemental work exists."""
    runtime, workflow, agent, _, ledger = initial_run
    agent.profile.capabilities.extend(["information_extraction", "analysis", "artifact_generation"])
    runtime.agent_registry.register(agent)
    runtime.runtime_binding_service.refresh_embedded_runtime()
    nodes = [
        PlannedTask(key="step:A", title="Understand", objective="Understand the repository review",
            capabilityRequirements=("task_understanding",)),
        PlannedTask(key="step:analysis", title="Analyze", objective="Analyze the inspected repository",
            capabilityRequirements=("analysis",)),
        PlannedTask(key="step:report", title="Report", objective="Deliver the repository review report",
            logicalRole="final_synthesis", capabilityRequirements=("artifact_generation",)),
    ]
    steps = [("A", "task_understanding", "task"), ("analysis", "analysis", "task"),
             ("report", "artifact_generation", "final_synthesis")]
    if with_scan:
        nodes.insert(1, PlannedTask(key="step:scan", title="Inspect",
            objective="Acquire the initial repository directory evidence", logicalRole="workspace_acquisition",
            capabilityRequirements=("information_extraction",),
            constraints=[{"workspaceReview": {"targets": [{"operation": "list", "path": "."}]}}]))
        steps.insert(1, ("scan", "information_extraction", "workspace_acquisition"))
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="workspace-multipage", name="Repository review",
        domain="general", runtimeEngine="acg", planningNodes=nodes,
        planningRelations=tuple(TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")
            for source, target in zip((node.key for node in nodes), (node.key for node in nodes[1:]))),
        steps=tuple(WorkflowStepDefinition(stepId=step_id, name=step_id, agentName=agent.profile.agent_name,
            capability=capability, logicalRole=role,
            outputSpec=runtime.capability_catalog.get(capability).output_contract)
            for step_id, capability, role in steps)))
    mission = runtime.create_mission("Read, review and report the repository", workflow_id="workspace-multipage")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="multipage-objective", expectedMissionRevision=0,
        objective="Read every authorized repository file, review the evidence and deliver a report",
        constraints=[], sourceRefs=[]))
    _, run = runtime.prepare_run(mission.mission_id, workflow_id="workspace-multipage")
    return runtime, workflow, agent, run, ledger


def _repository(service, monkeypatch):
    """Only the external mock changes; production signing and receipts run."""
    listings = {
        ".": [{"name": name, "type": kind} for name, kind in (
            ("README.md", "file"), ("src", "directory"), (".git", "directory"), (".cache", "directory"))],
        "src": [{"name": f"module_{index:02d}.py", "type": "file"} for index in range(35)],
        ".git": [{"name": "config", "type": "file"}],
        ".cache": [{"name": "state.json", "type": "file"}],
    }
    files = {"README.md": "Repository review fixture", ".git/config": "[core]\nbare = false",
             ".cache/state.json": '{"cache": true}'}
    files.update({f"src/module_{index:02d}.py": f"def module_{index:02d}():\n    return {index}\n"
                  for index in range(35)})
    service.files.update({("one", path): body for path, body in files.items()})
    original = type(service).__call__

    async def respond(instance, incoming):
        response = await original(instance, incoming)
        if incoming.method != "POST":
            return response
        result = response.json()
        receipt = result.get("receipt")
        if receipt and receipt["capabilityId"] == "fs.list":
            wire = instance.requests[-1]
            receipt["output"]["entries"] = listings[wire["input"]["path"]]
            receipt["checksum"] = receipt_checksum(receipt)
            previous_digest, _ = instance.ledger[wire["idempotencyKey"]]
            instance.ledger[wire["idempotencyKey"]] = previous_digest, result
            return httpx.Response(response.status_code, json=result)
        return response

    monkeypatch.setattr(type(service), "__call__", respond)
    return listings, files


def _report():
    text = "# Repository review\n\nAll authorized files were inspected in reviewed batches."
    return {"deliverable": {"title": "Repository review", "executiveSummary": text,
        "sections": [{"title": "Findings", "content": text, "sourceFields": ["analysis"]}],
        "calculations": [], "assumptions": [], "openQuestions": [], "sourceRefs": []},
        "final_answer": text,
        "verification": {"status": "passed", "checks": [], "unresolvedGaps": []},
        "artifact": {"artifactId": "repository-report", "type": "run_deliverable",
            "title": "Repository review", "mediaType": "text/markdown", "content": text,
            "structuredData": {}}}


@pytest.mark.asyncio
@pytest.mark.parametrize("with_scan", [True, False], ids=["declared-initial-reader", "understanding-only-prefix"])
async def test_multiple_signed_read_review_pages_preserve_prefix_and_execute_original_suffix(
        initial_run, hands_stack, monkeypatch, with_scan):
    listings, files = _repository(hands_stack.service, monkeypatch)
    runtime, workflow, agent, run = configure(_with_delivery_suffix(initial_run, with_scan=with_scan),
                                            hands_stack, monkeypatch)
    original = agent.run
    stages, review_coverage, observations, prefix_refs = [], [], [], {}

    def observe(*, observation, task_plan):
        observations.append(observation)
        return decide_runtime(observation=observation, task_plan=task_plan)

    runtime.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=observe)

    async def execute(context):
        stage = context.step.capability
        stages.append((context.step.step_id, stage))
        progress = workspace_observation_progress(context.run, runtime.execution_value_store)
        if stage == "information_extraction" and context.step.step_id != "scan" and not prefix_refs:
            prefix_refs.update({key: value for key, value in context.run.execution_state["outputRefs"].items()
                                if key in {"A", "scan"}})
        if stage in {"information_extraction", "verification"}:
            assert {tool.name for tool in context.tool_runtime.list_tools()} == {"fs.read", "fs.list"}
        if stage == "verification":
            agent.calls.append(context.step.step_id)
            review_coverage.append(progress[0])
            # An Agent can request a command despite the prompt. Enforce the
            # read-only semantic stage before dispatch, then permit real reads.
            requests_before = len(hands_stack.service.requests)
            with pytest.raises(ToolAuthorizationError):
                await context.tool_runtime.execute("shell.exec", {"command": "mock evidence count", "workdir": "."},
                    operation_key=context.commit_id + ":forbidden-command")
            assert len(hands_stack.service.requests) == requests_before
            records = []
            if progress[0]["verifiedReadCount"]:
                # Recheck one source without enumerating or rewriting the tree.
                checked = await context.tool_runtime.execute("fs.read", {"path": "README.md"},
                    operation_key=context.commit_id + ":targeted-review")
                records.append(checked.record)
            return AgentOutput(output={"verification": {"status": "passed", "checks": [
                {"criterion": "This evidence page is supported", "result": "passed",
                 "evidence": "Committed read receipts and targeted source review"}], "unresolved_gaps": []}},
                tool_executions=records)
        if stage in {"analysis", "artifact_generation"}:
            agent.calls.append(context.step.step_id)
            assert progress[0]["complete"] is True, {
                "stages": stages, "progress": progress,
                "observations": [(item.wake_reason, item.remaining_step_ids,
                    [(step.task_key, step.status, step.output_ref) for step in item.steps]) for item in observations],
            }
            assert progress[0]["verifiedReadCount"] == len(files)
            output = ({"analysis": {"findings": ["All files were inspected"], "assumptions": [], "gaps": []}}
                      if stage == "analysis" else _report())
            return AgentOutput(output=output)
        return await original(context)

    monkeypatch.setattr(agent, "run", execute)
    result = await runtime.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, {
        "error": result.error, "review": result.execution_state.get("reviewPayload"),
        "continuation": result.execution_state.get("workspaceReviewContinuation"),
    }
    assert result.run_id == run.run_id
    assert set(prefix_refs) == ({"A", "scan"} if with_scan else {"A"})
    assert all(result.execution_state["outputRefs"][key] == value for key, value in prefix_refs.items())
    assert all(count == 1 for count in Counter(agent.calls).values())
    assert stages[0] == ("A", "task_understanding")
    assert [capability for _, capability in stages[-2:]] == ["analysis", "artifact_generation"]
    if with_scan:
        assert stages[1] == ("scan", "information_extraction")
    assert [capability for _, capability in stages[2 if with_scan else 1:-2]] == [
        capability for _ in review_coverage for capability in ("information_extraction", "verification")]
    assert len(review_coverage) >= 4
    assert [item["verifiedReadCount"] for item in review_coverage] == sorted(
        item["verifiedReadCount"] for item in review_coverage)
    assert [item["verifiedListingCount"] for item in review_coverage] == sorted(
        item["verifiedListingCount"] for item in review_coverage)
    assert all("coverageInvalidation" not in item for item in review_coverage)
    assert review_coverage[-1]["verifiedReadCount"] == len(files)
    assert all(not item.failed_step_ids for item in observations)
    requests = hands_stack.service.requests
    assert {item["capabilityId"] for item in requests} == {"fs.list", "fs.read"}
    assert Counter(item["input"]["path"] for item in requests if item["capabilityId"] == "fs.list") == Counter(listings.keys())
    assert {item["input"]["path"] for item in requests if item["capabilityId"] == "fs.read"} == set(files)
    progress = workspace_observation_progress(result, runtime.execution_value_store)[0]
    assert progress["complete"] and progress["verifiedReadCount"] == len(files)
    assert progress["verifiedListingCount"] == len(listings)
    assert result.execution_state["graphVersion"] == len(review_coverage) + 1
    assert runtime.execution_dispatch_store.get(run.run_id).graph_version == result.execution_state["graphVersion"]
    # Re-entering a finished Run reuses every immutable result and receipt.
    calls_before, requests_before = list(agent.calls), len(requests)
    await runtime.execute_prepared_run(run.run_id)
    assert agent.calls == calls_before and len(requests) == requests_before
