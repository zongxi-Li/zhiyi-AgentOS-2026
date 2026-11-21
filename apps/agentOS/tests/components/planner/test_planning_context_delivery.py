"""Planner send views keep immutable context addressable without eager copies."""
from copy import deepcopy
import json

from components.planner.runtime_decision import decide_runtime
from components.planner.workspace_context import planning_workspace_material_context
from components.planner.workspace_discovery import workspace_planning_material
from contracts import stable_checksum
from contracts.runtime_planning import PlanningContextIndexEntry, PlanningResultField
from test_workspace_evidence_decisions import context, Model


def context_entry(index, kind="tool_receipt"):
    return PlanningContextIndexEntry(contextRef=f"tool:context-{index}", contextKind=kind,
        title=f"Saved {kind}", sourceRunId="run_evidence", stepId="read",
        originalRef=f"tool:original-{index}", status="available", trust="host_recorded",
        checksum=stable_checksum(index), byteLength=100_000, estimatedTokens=30_000,
        fields=tuple(PlanningResultField(name=f"field_{field}", present=True, valueType="dict",
            byteLength=10_000, estimatedTokens=3000) for field in range(10)))


def large_context():
    observation, plan = context(analysis_done=False)
    workspace = context_entry(1000, "workspace_material").model_copy(update={
        "original_ref": observation.workspace_discovery["contextRef"]})
    entries = tuple(context_entry(index) for index in range(1000)) + (workspace,)
    observation = observation.model_copy(update={"context_catalog": entries})
    material = {"sources": [{"sourceRef": "output:read", "findings": {"claim": "agent claim " * 10_000}}],
        "observations": [{"receiptRef": "tool:original-1", "tool": "fs.read", "path": "config.py",
            "output": {"text": "authenticated source payload " * 10_000}}]}
    return observation, plan, material


def test_default_planner_delivers_small_catalog_and_workspace_address_without_changing_authority():
    observation, plan, material = large_context()
    original = observation.model_dump(by_alias=True, mode="json")
    model = Model(lambda request: {"action": "continue", "observationId": request["observationId"],
        "reason": "Proceed with the declared intermediate analysis"})
    loads = []
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model,
        workspace_context_provider=lambda current: loads.append(current) or material,
        result_context_provider=lambda *_args, **_kwargs: None)
    request = model.requests[0]
    assert decision.action == "continue"
    assert request["observationId"] == observation.fingerprint()
    assert len(json.dumps(request, ensure_ascii=False)) < len(json.dumps(original, ensure_ascii=False)) / 5
    assert "field_9" not in json.dumps(request["observation"]["contextCatalog"])
    assert request["workspaceMaterials"]["contextRef"] == observation.context_catalog[-1].context_ref
    assert request["workspaceMaterials"]["delivery"] == "reference"
    assert "authenticated source payload" not in json.dumps(request)
    assert "agent claim" not in json.dumps(request)
    for key in ("steps", "remainingStepIds", "workspaceObservations", "goal", "graphVersion", "planVersion"):
        assert request["observation"][key] == original[key]
    assert observation.model_dump(by_alias=True, mode="json") == original
    assert loads == []


def test_legacy_planner_without_reader_keeps_material_and_complete_catalog():
    observation, plan, material = large_context()
    model = Model(lambda request: {"action": "continue", "observationId": request["observationId"],
        "reason": "Continue analysis"})
    decide_runtime(observation=observation, task_plan=plan, llm=model,
        workspace_context_provider=lambda _: material)
    request = model.requests[0]
    assert len(request["observation"]["contextCatalog"]) == len(observation.context_catalog)
    assert request["workspaceMaterials"] == workspace_planning_material(material)


def test_workspace_projection_does_not_create_an_unreadable_or_unavailable_address():
    observation, _, material = large_context()
    wrapped = workspace_planning_material(material)
    original = deepcopy(wrapped)
    assert planning_workspace_material_context(wrapped, observation) == original
    without = observation.model_copy(update={"context_catalog": observation.context_catalog[:-1]})
    assert planning_workspace_material_context(wrapped, without, readable=True) == original
    unavailable = observation.context_catalog[-1].model_copy(update={"status": "unavailable"})
    broken = observation.model_copy(update={"context_catalog": (unavailable,)})
    assert planning_workspace_material_context(wrapped, broken, readable=True) == original
    stale = observation.context_catalog[-1].model_copy(update={"original_ref": "tool:another-snapshot"})
    assert planning_workspace_material_context(wrapped, observation.model_copy(update={"context_catalog": (stale,)}),
        readable=True) == original
    assert wrapped == original


def test_react_delivers_the_same_catalog_and_workspace_address(tmp_path):
    from components.planner.react_loop import BoundedReActPlanningLoop
    from components.planner.unified_actions import PlannerActionGateway
    from support.acg.native_capabilities import build_default_capability_catalog
    from test_unified_actions import runtime_at

    runtime, store = runtime_at(tmp_path)
    observation, plan, material = large_context()
    # _build_prompt is a pure read projection; only allowedReads governs whether
    # the injected runtime can expand its references.
    from types import SimpleNamespace
    session = SimpleNamespace(session_id="session", allowed_reads={"step_output"}, actions_used=0)
    gateway = PlannerActionGateway(workflow_store=store, capability_catalog=build_default_capability_catalog(),
        result_context_provider=lambda *_args, **_kwargs: None)
    planner = BoundedReActPlanningLoop(llm=None, gateway=gateway)
    request = json.loads(planner._build_prompt(observation, plan, session, [],
        workspace_material=workspace_planning_material(material)))
    assert len(json.dumps(request)) < len(observation.model_dump_json()) / 5
    assert request["workspaceMaterials"]["contextRef"] == observation.context_catalog[-1].context_ref
    assert "authenticated source payload" not in json.dumps(request)
    assert "field_9" not in json.dumps(request["observation"]["contextCatalog"])
    assert request["observationId"] == observation.fingerprint()
