"""Native discovery and formal planning share the real signed execution path."""
# ruff: noqa: F811
from collections import Counter
from copy import deepcopy
import json

import pytest

from adapters.audited_tool_runtime import ToolAuthorizationError
from components.memory import MemoryService
from contracts import stable_checksum
from contracts.execution_evidence import workspace_observation_progress
from contracts.mission_semantic import MissionSemanticRequest
from contracts.planning import TaskPlan
from contracts.workspace_planning import effective_workspace_requirements
from contracts.workflow import WorkflowDefinition, WorkflowDefinitionType, WorkflowStatus
from service.agents.base import AgentOutput
from support.stores.execution_dispatch_store import DispatchCommand, SQLiteExecutionDispatchStore
from support.stores.execution_permit_store import SQLiteExecutionPermitStore
from _workspace_discovery_fixtures import install_repository, repository
from test_workspace_review_execution import hands_stack, initial_run, ready_boundary, runtime_boundary
from test_workspace_review_multipage import _report
from test_graph_handoff import attach as attach_handoff
from test_initial_graph_materialization import activate, materialize, setup_initial


FULL_SCOPE = {"path": ".", "kind": "directory", "operation": "read", "recursive": True}
DECOY_CONFIGURATION = "memory-claim-old-project-with-no-tests"


def _envelopes(value, key):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for item in value.values():
            yield from _envelopes(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _envelopes(item, key)


class DiscoveryPlannerModel:
    """Mock only the model boundary; parse/decompose/validation stay real."""

    provider = "offline"
    model = "workspace-discovery-integration"

    def __init__(self, repo, *, revise_scope=False):
        self.repo = repo
        self.requests = []
        self.formal_requests = []
        self.revise_scope = revise_scope
        self.scope_revision = None
        self.scope_revision_observed = False
        self.accepted_plan = None
        self.projected_requests = 0
        self.summarized_requests = 0

    def generate_json(self, prompt, schema, **kwargs):
        payload = json.JSONDecoder().raw_decode(prompt)[0]
        self.requests.append({"payload": deepcopy(payload), "schema": deepcopy(schema)})
        properties = schema.get("properties", {})
        grounded = self.repo.configuration_marker in prompt
        if grounded:
            if "primaryGoal" in properties or "tasks" in properties:
                self.formal_requests.append(deepcopy(payload))
                materials = [item for key in ("sourceMaterials", "materials")
                             for item in _envelopes(payload, key)
                             if isinstance(item, dict) and "trustClass" in item]
                assert materials and all(item["trustClass"] == "external_untrusted" for item in materials)
            evidence = [item for item in _envelopes(payload, "observations")
                        if isinstance(item, dict) and "trustClass" in item]
            assert evidence and evidence[0]["trustClass"] == "verified_evidence"
            observed = evidence[0]["content"]
            config = next(item for item in observed if item["path"] == "package.json")
            assert config["output"]["text"] == self.repo.files["package.json"]
            assert config["receiptRef"]
        if "primaryGoal" in properties:
            if any(_envelopes(payload, "sourceMaterials")):
                assert grounded, "Formal intent must receive actual configuration contents"
            return {"primaryGoal": "Review the repository and its actual configured test framework",
                "evidenceScope": "authorized_sources", "webExtraction": "snippets",
                "workspaceObservations": [{**FULL_SCOPE, **({"excludePaths": [".git"]
                    if self.revise_scope else [".git", ".cache"]} if grounded else {})}],
                "requiredCapabilities": ["task_understanding", "information_extraction", "analysis", "artifact_generation"],
                "expectedArtifacts": ["repository_review"], "keyConstraints": [],
                "verificationRequirements": [], "estimatedComplexity": "simple"}
        if "tasks" in properties:
            assert grounded, "Detailed work must be planned after signed discovery observations"
            tasks = [{"key": key, "title": title, "objective": objective, "capabilityId": capability,
                "logicalRole": role, "sourceRefs": ["artifact:1"] if capability == "artifact_generation" else [],
                "acceptanceCriteria": ["Trace the result to inspected source"],
                "decompositionRationale": "Use the observed configuration and preserve unread scope",
                **({"producedArtifacts": ["repository_review"]} if capability == "artifact_generation" else {})}
                for key, title, objective, capability, role in (
                    ("understand", "Confirm review plan", "Apply the observed project configuration to the review criteria",
                     "task_understanding", "understanding"),
                    ("inspect-source", "Inspect source", "Acquire representative source details for the code review",
                     "information_retrieval", "acquisition"),
                    ("analyze", "Analyze findings", "Assess defects using the committed reviewed source evidence",
                     "analysis", "analysis"),
                    ("report", "Write report", "Deliver the source review and configured test recommendations",
                     "artifact_generation", "final_synthesis"))]
            return {"tasks": tasks, "relations": [
                {"sourceKey": source["key"], "targetKey": target["key"], "relationType": "depends_on"}
                for source, target in zip(tasks, tasks[1:])], "controlPolicies": []}
        assert {"observationId", "action"} <= set(properties), properties
        observation = payload["observation"]
        accepted = TaskPlan.model_validate(self.accepted_plan()).model_dump(by_alias=True, mode="json")
        projection = payload["taskPlan"]["contextProjection"]
        assert projection["version"] == 1
        assert projection["acceptedPlanFingerprint"] == stable_checksum(accepted)
        assert payload["taskPlan"]["relations"] == accepted["relations"]
        assert [node["key"] for node in payload["taskPlan"]["nodes"]] == [node["key"] for node in accepted["nodes"]]
        assert payload["taskPlan"]["metadata"] == accepted["metadata"]
        self.projected_requests += 1
        self.summarized_requests += projection["summarizedNodeCount"] > 0
        assert not observation.get("failedStepIds"), observation.get("failureMessage")
        assert not observation.get("planningCommitRejection"), observation.get("planningCommitRejection")
        if self.revise_scope and self.scope_revision is None:
            acquisition_keys = {node["key"] for node in payload["taskPlan"]["nodes"]
                                if node["logicalRole"] == "workspace_acquisition"}
            acquired = [step for step in observation["steps"]
                        if step["taskKey"] in acquisition_keys and step["status"] == "completed"]
            if acquired:
                assert observation["planVersion"] == observation["graphVersion"] == 2
                ignore = next(item for item in observed if item["path"] == ".gitignore")
                assert ".cache/" in ignore["output"]["text"]
                self.scope_revision = {"taskPlan": deepcopy(payload["taskPlan"]),
                                       "observation": deepcopy(observation)}
                return {"observationId": payload["observationId"], "action": "revise",
                    "reason": "The inspected ignore configuration identifies the generated cache subtree",
                    "taskPlanPatch": {"missionId": observation["missionId"], "basePlanVersion": 2,
                        "planVersion": 3, "metadata": {"workspaceScope": {"version": 1,
                            "requirements": [{**FULL_SCOPE, "excludePaths": [".git", ".cache"]}],
                            "rationale": "The committed .gitignore identifies .cache as generated project state; "
                                "retain source, configuration and all unread relevant work.",
                            "sourceRefs": [ignore["receiptRef"], acquired[0]["outputRef"]]}}}}
            return {"observationId": payload["observationId"], "action": "continue",
                    "reason": "Inspect the already scheduled source before refining the inferred scope"}
        if self.scope_revision is not None and not self.scope_revision_observed:
            assert observation["planVersion"] == observation["graphVersion"] == 3
            assert payload["taskPlan"]["nodes"] == self.scope_revision["taskPlan"]["nodes"]
            assert payload["taskPlan"]["relations"] == self.scope_revision["taskPlan"]["relations"]
            assert projection["acceptedPlanFingerprint"] != (
                self.scope_revision["taskPlan"]["contextProjection"]["acceptedPlanFingerprint"])
            before_refs = {step["stepId"]: step["outputRef"]
                           for step in self.scope_revision["observation"]["steps"] if step["outputRef"]}
            assert all(step["outputRef"] == before_refs[step["stepId"]]
                       for step in observation["steps"] if step["stepId"] in before_refs)
            assert observation["workspaceObservations"][0]["verifiedReadCount"] == (
                self.scope_revision["observation"]["workspaceObservations"][0]["verifiedReadCount"])
            self.scope_revision_observed = True
        fallback = payload.get("workspaceReviewFallback", {})
        if fallback.get("action") == "revise":
            return deepcopy(fallback)
        action = "continue" if observation["remainingStepIds"] else "complete"
        if action == "complete":
            assert not observation["completionBlockers"], observation["completionBlockers"]
        return {"observationId": payload["observationId"], "action": action,
                "reason": "Execute the accepted remaining work or complete after all evidence gates pass"}


def _native_run(initial_run, model, *, explicit_scope):
    runtime, workflow, agent, _, ledger = initial_run
    agent.profile.capabilities.extend(["information_extraction", "analysis", "artifact_generation"])
    runtime.agent_registry.register(agent)
    runtime.runtime_binding_service.refresh_embedded_runtime()
    runtime.resource_plane.set_runtime_enabled("runtime:horizon-test", enabled=False)
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="workspace-discovery", name="Workspace review",
        domain="general", runtimeEngine="acg", definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP))
    runtime.set_intent_llm(model)
    mission = runtime.create_mission("Review repository source", workflow_id="workspace-discovery")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="discovery-review-objective", expectedMissionRevision=0,
        objective="Review repository source using actual project configuration and produce a complete report",
        constraints=[], sourceRefs=[]))
    payload = {"workspaceBinding": {"workspaceId": "one", "grantId": "grant-one"}}
    if explicit_scope:
        payload["workspaceObservations"] = [dict(FULL_SCOPE)]
    _, run = runtime.prepare_run(mission.mission_id, workflow_id="workspace-discovery", input_override=payload)
    return runtime, workflow, agent, run, ledger


def _admit(initial_context, transport):
    """Exercise every production admission authority without doing host I/O."""
    assert not transport.observations
    context = setup_initial(initial_context)
    runtime, workflow, agent, run, commitment, _, _ = context
    assert commitment.proposal_type == "initial_plan" and commitment.proposal_payload.plan_version == 1
    assert {node.logical_role for node in commitment.proposal_payload.nodes} == {"understanding", "workspace_discovery"}
    assert not transport.observations
    compiled = materialize(context)
    assert not transport.observations
    activation = activate(context, compiled)
    assert not transport.observations
    attach_handoff(runtime, workflow)
    SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
    runtime.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    handoff = runtime.prepare_graph_handoff(activation.activation_id, idempotency_key="discovery-initial-handoff")
    assert handoff.status == "STATE_PREPARED", handoff
    assert not transport.observations
    permit = runtime.issue_execution_permit(handoff.handoff_id, idempotency_key="discovery-initial-permit")
    assert permit.status == "ISSUED", permit
    assert not transport.observations
    SQLiteExecutionDispatchStore.upgrade_schema(workflow.db_path)
    runtime.execution_dispatch_store = SQLiteExecutionDispatchStore(workflow.db_path)
    runtime.execution_dispatch_enabled = True
    current = workflow.get_run(run.run_id)
    principal = runtime.semantic_principal_provider()
    command = DispatchCommand(dispatch_id="discovery:dispatch", operation_key="discovery-initial-dispatch",
        request_fingerprint="discovery-initial", mission_id=run.mission_id, run_id=run.run_id,
        permit_id=permit.permit_id, graph_id=current.execution_state["graphId"], graph_version=1,
        runtime_revision=current.runtime_revision, actor_id=principal.actor_id, tenant_id=principal.tenant_id)
    runtime.execution_dispatch_store.accept(command, runtime.execution_permit_authority.assert_dispatchable)
    assert not transport.observations
    return runtime, workflow, agent, current


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_scope,revise_scope", [(False, False), (True, False), (False, True)],
    ids=["inferred-source-scope", "explicit-full-scope", "review-refines-inferred-scope"])
async def test_native_discovery_is_admitted_before_reading_then_plans_and_completes_same_run(
        initial_run, hands_stack, monkeypatch, explicit_scope, revise_scope):
    repo = repository(git_fanout=0 if explicit_scope else 80, cache_fanout=0 if explicit_scope else 12)
    transport = install_repository(hands_stack, monkeypatch, repo,
        forbidden_prefixes=() if explicit_scope else (".git", ".cache"))
    model = DiscoveryPlannerModel(repo, revise_scope=revise_scope)
    initial_context = _native_run(initial_run, model, explicit_scope=explicit_scope)
    runtime, workflow, agent, run, _ = initial_context
    hands_stack.runtime.execution_value_store = runtime.execution_value_store
    runtime.tool_runtime = hands_stack.tools
    runtime, workflow, agent, run = _admit(initial_context, transport)
    model.accepted_plan = lambda: workflow.get_run(run.run_id).execution_state["taskPlan"]
    frozen_requirements, frozen_input = deepcopy(run.execution_state["workspaceObservations"]), deepcopy(run.input)
    memory = MemoryService(store=runtime.memory_store)
    memory.remember_step_output(run_id=run.run_id, step_id="historical-memory-only",
        output={"finding": DECOY_CONFIGURATION, "claimedReadPaths": list(repo.files), "complete": True})
    assert workspace_observation_progress(run, runtime.execution_value_store)[0]["verifiedReadCount"] == 0
    assert not workspace_observation_progress(run, runtime.execution_value_store)[0]["complete"]
    prefix_ids = {step.step_id for step in run.steps}
    stages, review_progress, prefix_refs, formal_plans = [], [], {}, []

    def record_dispatch(wire):
        current = workflow.get_run(run.run_id)
        dispatch = runtime.execution_dispatch_store.get(run.run_id)
        assert dispatch and dispatch.graph_version == current.execution_state["graphVersion"]
        assert wire["identity"]["runId"] == run.run_id
        return {"graphVersion": current.execution_state["graphVersion"], "stepId": wire["identity"]["stepId"]}

    transport.before_dispatch = record_dispatch

    async def execute(context):
        capability = context.step.capability
        graph_version = context.run.execution_state["graphVersion"]
        stages.append((context.step.step_id, capability, context.step.logical_role, graph_version))
        plan = TaskPlan.model_validate(context.run.execution_state["taskPlan"])
        progress = workspace_observation_progress(context.run, runtime.execution_value_store)[0]
        if graph_version >= 2 and not prefix_refs:
            prefix_refs.update({key: value for key, value in context.run.execution_state["outputRefs"].items()
                                if key in prefix_ids})
        if graph_version == 2 and not formal_plans:
            formal_plans.append(plan)
            assert plan.metadata["workspaceDiscovery"]["phase"] == "formal"
            if revise_scope:
                assert set(effective_workspace_requirements(context.run)[0].exclude_paths) == {".git"}
        if capability == "task_understanding":
            return AgentOutput(output={"task_summary": "Review the actual source, configuration and unresolved scope",
                                       "constraints": []})
        records, facts = [], []
        if capability == "information_extraction":
            assert {tool.name for tool in context.tool_runtime.list_tools()} == {"fs.read", "fs.list"}
            if context.step.logical_role == "workspace_discovery":
                assert graph_version == 1
                targets = [{"operation": "list", "path": "."}] + [
                    {"operation": "read", "path": path}
                    for path in ("README.md", "package.json", "pyproject.toml", ".gitignore")]
            else:
                task_key = next(item["planNodeKey"] for item in context.run.execution_state["taskBindings"]
                                if item["acgNodeId"] == context.step.step_id)
                task = next(node for node in plan.nodes if node.key == task_key)
                targets = next((item["workspaceReview"]["targets"] for item in task.constraints
                                if "workspaceReview" in item), [{"operation": "read", "path": "src/module_00.py"}])
            for index, target in enumerate(targets):
                read = await context.tool_runtime.execute("fs." + target["operation"], {"path": target["path"]},
                    operation_key=f"{context.commit_id}:acquire:{index}")
                records.append(read.record)
                facts.append({"name": "observed path", "value": target["path"], "source": read.record["receiptRef"]})
            # Deliberately omit the configuration marker: the formal planner
            # must receive authenticated file contents, not just this summary.
            return AgentOutput(output={"extracted_information": {"facts": facts, "metrics": [], "entities": [],
                "unknowns": ["Other source files remain unread"]}}, tool_executions=records)
        if capability == "verification":
            review_progress.append(deepcopy(progress))
            assert {tool.name for tool in context.tool_runtime.list_tools()} == {"fs.read", "fs.list"}
            with pytest.raises(ToolAuthorizationError):
                await context.tool_runtime.execute("shell.exec", {"command": "mock evidence check", "workdir": "."},
                    operation_key=context.commit_id + ":forbidden-shell")
            return AgentOutput(output={"verification": {"status": "passed", "checks": [
                {"criterion": "This evidence page is supported", "result": "passed", "evidence": "Committed source receipts"}],
                "unresolved_gaps": []}})
        assert capability in {"analysis", "artifact_generation"}, capability
        assert progress["complete"], progress
        return AgentOutput(output={"analysis": {"findings": ["Reviewed the configured source"], "assumptions": [], "gaps": []}}
            if capability == "analysis" else _report())

    monkeypatch.setattr(agent, "run", execute)
    result = await runtime.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, json.dumps({"error": result.error,
        "review": result.execution_state.get("reviewPayload"),
        "continuation": result.execution_state.get("workspaceReviewContinuation"),
        "rejection": result.execution_state.get("planningCommitRejection"),
        "failure": (result.execution_state.get("planningLoop") or {}).get("current", {}).get("failure")})
    assert result.run_id == run.run_id and set(prefix_refs) == prefix_ids
    assert result.execution_state["workspaceObservations"] == frozen_requirements and result.input == frozen_input
    assert all(result.execution_state["outputRefs"][key] == value for key, value in prefix_refs.items())
    assert all(count == 1 for count in Counter(stage[0] for stage in stages).values())
    assert len([stage for stage in stages if stage[2] == "workspace_discovery"]) == 1
    assert len([stage for stage in stages if stage[1] == "task_understanding"]) == 1
    assert [stage[1] for stage in stages[-2:]] == ["analysis", "artifact_generation"]
    assert formal_plans and review_progress and model.formal_requests
    assert model.projected_requests and model.summarized_requests
    assert all(item["snapshot"]["graphVersion"] >= 1 for item in transport.observations)
    assert {item["tool"] for item in transport.observations} == {"fs.list", "fs.read"}
    assert transport.paths("fs.list")["."] == 1
    assert all(count == 1 for count in transport.paths("fs.list").values())
    assert [item["verifiedReadCount"] for item in review_progress] == sorted(
        item["verifiedReadCount"] for item in review_progress)
    assert all("coverageInvalidation" not in item for item in review_progress)
    requirements = effective_workspace_requirements(result)
    assert len(requirements) == 1
    assert set(requirements[0].exclude_paths) == (set() if explicit_scope else {".git", ".cache"})
    expected_files = {path for path in repo.files if explicit_scope or not path.startswith((".git/", ".cache/"))}
    assert set(transport.paths("fs.read")) == expected_files
    assert all(count == 1 for count in transport.paths("fs.read").values())
    final_progress = workspace_observation_progress(result, runtime.execution_value_store)[0]
    assert final_progress["complete"] and final_progress["verifiedReadCount"] == len(expected_files)
    assert result.execution_state["graphVersion"] > 2
    if revise_scope:
        assert model.scope_revision_observed
        assert any(stage[1:4] == ("information_extraction", "workspace_acquisition", 2) for stage in stages)
        before_refs = {step["stepId"]: step["outputRef"]
                       for step in model.scope_revision["observation"]["steps"] if step["outputRef"]}
        assert all(result.execution_state["outputRefs"][key] == ref for key, ref in before_refs.items())
    assert "grant-one" not in json.dumps(model.requests, ensure_ascii=False)
    observed_request_count, observed_stage_count = len(transport.observations), len(stages)
    await runtime.execute_prepared_run(run.run_id)
    assert len(transport.observations) == observed_request_count and len(stages) == observed_stage_count
