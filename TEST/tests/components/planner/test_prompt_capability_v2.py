from __future__ import annotations

import pytest

from components.planner.complexity import assess_complexity
from components.planner.intent_analyzer import INTENT_PROFILE_PROMPT_VERSION, IntentParser
from support.packs.native_capabilities import NATIVE_CAPABILITY_IDS, build_default_capability_catalog


def test_intent_parser_preserves_typed_evidence_boundary():
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            assert "evidenceScope" in schema["required"]
            return {"primaryGoal": "Use supplied facts", "requiredCapabilities": ["analysis"],
                    "estimatedComplexity": "simple", "evidenceScope": "task_input_only", "webExtraction": "snippets"}

    profile = IntentParser(llm=Model()).parse(intent="Use supplied facts")
    assert profile.evidence_scope == "task_input_only"
    assert profile.model_dump(by_alias=True)["webExtraction"] == "snippets"


@pytest.mark.parametrize("model_origin,caller_scope,literal_file,expected_origin", [
    ("inferred", False, False, "inferred"),
    ("explicit", False, False, "explicit"),
    ("inferred", True, False, "explicit"),
    ("explicit", False, True, "explicit"),
])
def test_workspace_origin_reaches_discovery_without_overriding_caller_evidence(
    model_origin, caller_scope, literal_file, expected_origin,
):
    from components.planner.workspace_discovery import build_workspace_discovery_plan
    from contracts.workspace_planning import validate_workspace_plan_revision

    requirement = ({"path": "src/main.py", "kind": "file", "operation": "read"} if literal_file else
        {"path": ".", "kind": "directory", "operation": "read", "recursive": True})

    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            # New model requests make this classification explicit; it is not
            # inferred from the mere presence of a workspace address by the host.
            assert "workspaceScopeOrigin" in schema["required"]
            return {"primaryGoal": "Inspect the requested source", "requiredCapabilities": ["analysis"],
                "evidenceScope": "authorized_sources", "webExtraction": "snippets",
                "estimatedComplexity": "medium", "workspaceObservations": [requirement],
                "workspaceScopeOrigin": model_origin}

    task_input = {"workspaceBinding": {"workspaceId": "selected-folder", "grantId": "grant",
        "workspaceRoot": "C:/projects/selected-folder"}}
    if caller_scope:
        task_input["workspaceObservations"] = [requirement]
    intent = ("阅读 src/main.py" if literal_file else
        "Read every file including VCS and caches" if model_origin == "explicit" else
        "仔细阅读这个文件夹中的代码，梳理依赖并给出勘察报告")
    profile = IntentParser(llm=Model()).parse(intent=intent, task_input=task_input)
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    assert plan.metadata["workspaceDiscovery"]["scopeOrigin"] == expected_origin
    metadata = {**plan.metadata,
        "workspaceDiscovery": {**plan.metadata["workspaceDiscovery"], "phase": "formal"},
        "workspaceScope": {"version": 1, "requirements": [{
            "path": ".", "kind": "directory", "operation": "read", "recursive": True,
            "excludePaths": ["src/main.py" if literal_file else ".git"]}],
            "rationale": "Committed discovery identified the relevant source scope",
            "sourceRefs": ["output:discovery"]}}
    if expected_origin == "explicit":
        with pytest.raises(ValueError, match="cannot reduce explicit"):
            validate_workspace_plan_revision(plan, metadata)
    else:
        assert validate_workspace_plan_revision(plan, metadata) is None


def test_workspace_origin_request_contract_keeps_legacy_and_offline_profiles_readable():
    from components.planner.workspace_discovery import build_workspace_discovery_plan
    from contracts.acg.semantic_profile import TaskSemanticProfile

    legacy = {"primaryGoal": "Review source", "workspaceObservations": [
        {"path": ".", "kind": "directory", "operation": "read", "recursive": True}]}
    profile = TaskSemanticProfile.model_validate(legacy)
    assert profile.workspace_scope_origin is None
    assert "workspaceScopeOrigin" not in profile.model_dump(by_alias=True)
    task_input = {"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}}
    offline = IntentParser().parse(intent="审查仓库代码依赖", use_llm=False, task_input=task_input)
    assert offline.workspace_scope_origin == "inferred"
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", offline, task_input)
    assert plan.metadata["workspaceDiscovery"]["scopeOrigin"] == "inferred"


def test_all_existing_capabilities_have_a_versioned_prompt_profile() -> None:
    catalog = build_default_capability_catalog()

    assert len(NATIVE_CAPABILITY_IDS) == 15
    for capability_id in NATIVE_CAPABILITY_IDS:
        profile = catalog.get(capability_id).prompt_profile
        assert profile.prompt_profile_version == "capability-profile.v2"
        assert profile.purpose
        assert profile.quality_criteria
        assert profile.verification_questions


def test_intent_prompt_exposes_selection_boundaries_and_quality() -> None:
    prompt = IntentParser(capability_catalog=build_default_capability_catalog()).build_prompt(
        intent="比较三套方案并给出有证据的报告",
        domain="general",
        task_type="general",
        task_input={"constraints": ["预算不得超过上限"], "expectedArtifacts": ["比较报告"]},
    )

    assert INTENT_PROFILE_PROMPT_VERSION in prompt
    assert '"whenToUse"' in prompt
    assert '"whenNotToUse"' in prompt
    assert '"qualityCriteria"' in prompt
    assert "比较报告" in prompt


def test_complexity_uses_six_axes_instead_of_text_length() -> None:
    assessment = assess_complexity(
        intent="并行设计三套候选方案，比较迭代，完成安全审计和验收",
        task_input={
            "constraints": [f"constraint-{index}" for index in range(8)],
            "expectedArtifacts": [f"artifact-{index}" for index in range(6)],
            "sourceMaterials": ["meter-data", "load-data", "risk-register"],
        },
        profile_data={
            "requiredCapabilities": [f"cap-{index}" for index in range(10)],
            "verificationRequirements": ["evidence", "calculation", "acceptance"],
        },
    )

    assert assessment.level.value == "complex"
    assert set(assessment.dimensions) == {
        "goals_and_artifacts",
        "hard_constraints",
        "evidence_and_tools",
        "cross_stage_dependencies",
        "alternatives_parallel_iteration",
        "risk_and_review",
    }
    assert len(assessment.reasons) == 6


def test_business_output_contracts_have_no_generic_expression_caps() -> None:
    def forbidden_paths(value, path=""):
        hits = []
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}" if path else key
                if key in {"maxItems", "maxLength"}:
                    hits.append(child)
                hits.extend(forbidden_paths(item, child))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                hits.extend(forbidden_paths(item, f"{path}[{index}]"))
        return hits

    catalog = build_default_capability_catalog()
    for capability_id in NATIVE_CAPABILITY_IDS:
        assert forbidden_paths(catalog.get(capability_id).output_contract) == []
