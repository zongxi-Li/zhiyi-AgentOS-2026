from adapters.model.native_prompt import (
    ARTIFACT_SYNTHESIS_PROMPT_VERSION,
    NATIVE_CAPABILITY_PROMPT_VERSION,
    VERIFICATION_PROMPT_VERSION,
    NativeCapabilityPromptBuilder,
)
from support.acg.models import build_default_capability_catalog


def test_native_v3_prompt_preserves_planned_task_semantics_without_expression_caps() -> None:
    descriptor = build_default_capability_catalog().get("cost_analysis")
    prompt = NativeCapabilityPromptBuilder().build(
        capability_descriptor=descriptor,
        step_goal="Calculate candidate A lifecycle cost",
        acceptance_criteria=["Formula, inputs, units and assumptions are present"],
        source_refs=["meter-data"],
        logical_role="alternative-analysis",
        task_title="Mission",
        task_input={"constraints": ["budget cap"], "expectedArtifacts": ["cost table"]},
        context_data={},
        source_data={},
        evidence_refs=[],
        output_schema=descriptor.output_contract,
    )

    assert NATIVE_CAPABILITY_PROMPT_VERSION == "native-capability.v3"
    assert VERIFICATION_PROMPT_VERSION == "verification.v2"
    assert ARTIFACT_SYNTHESIS_PROMPT_VERSION == "artifact-synthesis.v3"
    assert "Calculate candidate A lifecycle cost" in prompt
    assert "Formula, inputs, units and assumptions are present" in prompt
    assert "budget cap" in prompt and "cost table" in prompt
    assert '"requestType":"ExecutionRequest"' in prompt
    assert '"trustClass":"runtime_authoritative"' in prompt
    assert "at most 8" not in prompt
    assert "under 400" not in prompt
    assert "Prompt version" not in prompt
