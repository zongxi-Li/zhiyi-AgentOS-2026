from __future__ import annotations

from components.planner.complexity import assess_complexity
from components.planner.intent_analyzer import INTENT_PROFILE_PROMPT_VERSION, IntentParser
from support.acg.models import NATIVE_CAPABILITY_IDS, build_default_capability_catalog


def test_intent_parser_preserves_typed_evidence_boundary():
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            assert "evidenceScope" in schema["required"]
            return {"primaryGoal": "Use supplied facts", "requiredCapabilities": ["analysis"],
                    "estimatedComplexity": "simple", "evidenceScope": "task_input_only", "webExtraction": "snippets"}

    profile = IntentParser(llm=Model()).parse(intent="Use supplied facts")
    assert profile.evidence_scope == "task_input_only"
    assert profile.model_dump(by_alias=True)["webExtraction"] == "snippets"


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
