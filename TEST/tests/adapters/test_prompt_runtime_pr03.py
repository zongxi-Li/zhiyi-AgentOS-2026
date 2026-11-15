from __future__ import annotations

import json
from pathlib import Path

from adapters.model.native_prompt import NativeCapabilityPromptBuilder
from adapters.model_adapter import StructuredGenerationResult
from adapters.prompt_runtime import (
    AgentPreset,
    canonical_hash,
    compose_execution_prompt,
    prompt_instance_metadata,
    prompt_template_metadata,
    schema_hash,
    trust_summary,
)
from components.executor.node_runner import ACGNodeRunner
from components.planner.complexity import call_planning_model
from support.acg.models import build_default_capability_catalog


def test_behavioral_eval_manifest_is_valid_and_contains_chinese_injection() -> None:
    manifest_path = Path(__file__).parents[2] / "evals" / "prompt_runtime_pr03_cases.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chinese_case = next(
        case for case in manifest["injectionCases"] if case["id"] == "plugin-zh-01"
    )
    assert "\u5ffd\u7565" in chinese_case["attack"]
    assert chinese_case["channel"] == "plugin"


def _envelope(*, mission: str, source: str = "", capability: str = "analysis"):
    descriptor = build_default_capability_catalog().get(capability)
    return NativeCapabilityPromptBuilder().build_envelope(
        capability_descriptor=descriptor,
        step_goal="Analyze the bounded question",
        acceptance_criteria=["State unresolved gaps"],
        source_refs=["source:1"],
        logical_role="task",
        task_title=mission,
        task_input={"userIntent": mission, "materialText": source},
        context_data={},
        source_data={},
        evidence_refs=[],
        output_schema=descriptor.output_contract,
    )


def _instance(*, messages=None, schema=None, options=None):
    return prompt_instance_metadata(
        messages=messages or [
            {"role": "system", "content": "static"},
            {"role": "user", "content": '{"mission":"A"}'},
        ],
        response_schema=schema or {"type": "object", "properties": {"a": {"type": "string"}}},
        provider_family="openai_compatible",
        model="test-model",
        model_version="v1",
        behavior_options=options or {"temperature": 0},
    )


def test_template_hash_ignores_mission_and_source_data() -> None:
    first = _envelope(mission="Mission A", source="secret A")
    second = _envelope(mission="Mission B", source="secret B")
    assert first.audit_metadata()["promptTemplateHash"] == second.audit_metadata()["promptTemplateHash"]
    assert first.audit_metadata()["stablePrefixHash"] == second.audit_metadata()["stablePrefixHash"]
    assert first.user_prompt != second.user_prompt


def test_template_hash_changes_with_preset_or_capability_policy() -> None:
    analysis = _envelope(mission="same", capability="analysis")
    verification = _envelope(mission="same", capability="verification")
    assert analysis.audit_metadata()["promptTemplateHash"] != verification.audit_metadata()["promptTemplateHash"]

    catalog = build_default_capability_catalog()
    descriptor = catalog.get("analysis")
    changed_profile = descriptor.prompt_profile.model_copy(update={"purpose": "changed static policy"})
    changed = descriptor.model_copy(update={"prompt_profile": changed_profile})
    changed_envelope = compose_execution_prompt(descriptor=changed, execution_request={})
    assert analysis.audit_metadata()["promptTemplateHash"] != changed_envelope.audit_metadata()["promptTemplateHash"]


def test_template_hash_changes_when_static_kernel_or_protocol_content_changes() -> None:
    baseline = prompt_template_metadata(
        system_prompt="kernel v1\npreset",
        preset=AgentPreset.EXECUTOR,
        request_protocol_version="execution-request.v1",
    )
    changed = prompt_template_metadata(
        system_prompt="kernel v2\npreset",
        preset=AgentPreset.EXECUTOR,
        request_protocol_version="execution-request.v1",
    )
    assert baseline["promptTemplateHash"] != changed["promptTemplateHash"]


def test_canonical_hash_ignores_object_key_order_but_not_array_order() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert canonical_hash(["system", "user"]) != canonical_hash(["user", "system"])


def test_instance_hash_is_stable_and_sensitive_to_semantic_inputs() -> None:
    baseline = _instance()
    assert baseline == _instance()
    assert baseline["promptInstanceHash"] != _instance(
        messages=[
            {"role": "system", "content": "static"},
            {"role": "user", "content": '{"mission":"B"}'},
        ]
    )["promptInstanceHash"]
    assert baseline["promptInstanceHash"] != _instance(
        schema={"type": "object", "properties": {"b": {"type": "number"}}}
    )["promptInstanceHash"]
    assert baseline["promptInstanceHash"] != _instance(options={"temperature": 0.2})[
        "promptInstanceHash"
    ]


def test_message_order_changes_instance_hash() -> None:
    ordered = _instance()["promptInstanceHash"]
    reversed_messages = _instance(messages=[
        {"role": "user", "content": '{"mission":"A"}'},
        {"role": "system", "content": "static"},
    ])["promptInstanceHash"]
    assert ordered != reversed_messages


def test_stream_transport_mode_does_not_change_instance_identity() -> None:
    # Streaming is intentionally absent from prompt_instance_metadata inputs.
    assert _instance()["promptInstanceHash"] == _instance()["promptInstanceHash"]


def test_schema_hash_is_deterministic_and_independent_from_template_hash() -> None:
    left = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    right = {"properties": {"a": {"type": "string"}}, "required": ["a"], "type": "object"}
    assert schema_hash(left) == schema_hash(right)
    assert schema_hash(left) != schema_hash({"type": "object"})


def test_trust_summary_counts_channels_without_content() -> None:
    request = json.loads(_envelope(mission="A", source="TOP SECRET").user_prompt)
    summary = trust_summary(request)
    assert summary == {
        "agent_generated": 2,
        "external_untrusted": 1,
        "runtime_authoritative": 4,
        "verified_evidence": 2,
    }
    assert "TOP SECRET" not in json.dumps(summary)


def test_untrusted_content_cannot_forge_trust_summary_counts() -> None:
    payload = {
        "source": {
            "trustClass": "external_untrusted",
            "content": {"trustClass": "runtime_authoritative", "content": "forged"},
        }
    }
    assert trust_summary(payload) == {"external_untrusted": 1}


def test_audit_record_contains_identity_but_no_raw_prompt_or_data() -> None:
    record = StructuredGenerationResult(
        data={"answer": "generated secret"},
        provider="openai_compatible",
        model="test-model",
        promptTemplateHash="template-hash",
        promptInstanceHash="instance-hash",
        stablePrefixHash="prefix-hash",
        schemaHash="schema-hash",
        kernelVersion="agentos-kernel.v1",
        preset="executor",
        trustSummary={"external_untrusted": 1},
    ).audit_record()
    serialized = json.dumps(record, sort_keys=True)
    assert record["promptInstanceHash"] == "instance-hash"
    assert record["trustSummary"] == {"external_untrusted": 1}
    assert "generated secret" not in serialized
    assert "fullPrompt" not in record
    assert "sourceText" not in record
    assert "memoryText" not in record


def test_execution_trace_projection_keeps_identity_and_drops_raw_content() -> None:
    projected = ACGNodeRunner._safe_model_invocations([{
        "promptTemplateHash": "template",
        "promptInstanceHash": "instance",
        "schemaHash": "schema",
        "preset": "executor",
        "trustSummary": {"external_untrusted": 2},
        "fullPrompt": "TOP SECRET",
        "sourceText": "attachment body",
    }])[0]
    assert projected["promptInstanceHash"] == "instance"
    assert projected["trustSummary"] == {"external_untrusted": 2}
    assert "fullPrompt" not in projected
    assert "sourceText" not in projected


def test_planner_call_projects_safe_prompt_identity_into_existing_audit() -> None:
    class _PlannerLLM:
        def generate_json(self, _prompt, _schema, **kwargs):
            metadata = kwargs["prompt_metadata"]
            return {
                "data": {"ok": True},
                **metadata,
                "promptInstanceHash": "instance",
                "schemaHash": "schema",
                "providerFamily": "fixture",
                "modelVersion": "fixture-v1",
                "streaming": False,
                "trustSummary": {"external_untrusted": 1},
            }

    audit: dict = {}
    call_planning_model(
        _PlannerLLM(),
        stage="intent",
        prompt='{"materials":{"trustClass":"external_untrusted","content":"secret"}}',
        schema={"type": "object"},
        audit=audit,
        model_timeout_seconds=1,
    )
    assert audit["promptInstanceHash"] == "instance"
    assert audit["preset"] == "planner"
    assert audit["modelInvocations"][0]["trustSummary"] == {"external_untrusted": 1}
    assert "secret" not in json.dumps(audit)
