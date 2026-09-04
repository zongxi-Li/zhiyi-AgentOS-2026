"""模型调用安全审计元数据测试。"""

from __future__ import annotations

from adapters.model_adapter import StructuredGenerationResult


def test_model_audit_record_excludes_prompt_and_generated_data() -> None:
    """审计记录只保留成本与版本元数据，不能含 prompt 或模型生成正文。"""
    record = StructuredGenerationResult(
        data={"answer": "secret"},
        provider="local",
        model="test",
        usage={"tokens": 3},
    ).audit_record()

    assert record["provider"] == "local"
    assert record["model"] == "test"
    assert record["latencyMs"] == 0
    assert record["promptVersion"] == "native-capability.v3"
    assert record["promptTemplateHash"] == ""
    assert record["usage"] == {"tokens": 3}
    assert record["outputPolicy"] == "api_controlled"
    assert record["effectiveReason"] == "provider_default"
    assert record["outputExhausted"] is False
    assert "answer" not in record
    assert "secret" not in str(record)
