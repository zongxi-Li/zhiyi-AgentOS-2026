from __future__ import annotations

from benchmarks.competition_2026.smoke_one import (
    communication_metrics,
    extract_prediction,
    length_bucket,
    qa_f1,
    score_hotpotqa,
)


def test_hotpotqa_f1_matches_normalized_token_overlap() -> None:
    assert qa_f1("The Albert Einstein", "Albert Einstein") == 1.0
    assert score_hotpotqa("Einstein", ["Albert Einstein", "Einstein"]) == 1.0


def test_length_bucket_uses_longbench_e_boundaries() -> None:
    assert length_bucket(3999) == "0-4k"
    assert length_bucket(4000) == "4-8k"
    assert length_bucket(7999) == "4-8k"
    assert length_bucket(8000) == "8k+"


def test_prediction_extraction_uses_fixed_preferred_field_order() -> None:
    assert extract_prediction({"report": "fallback", "answer": "gold"}) == "gold"
    assert extract_prediction({"deliverable": {"finalAnswer": "nested"}}) == "nested"


def test_communication_metrics_excludes_runtime_interaction_mirror() -> None:
    provenance = {
        "integrityStatus": "valid",
        "events": [
            {
                "eventType": "data_consumed",
                "payload": {
                    "eventId": "cons_000001",
                    "tokensDelivered": 100,
                    "tokensAvailable": 400,
                    "savingRatio": 0.75,
                },
            },
            {
                "eventType": "data_consumed",
                "payload": {
                    "eventId": "int_000002",
                    "interactionId": "int_000002",
                    "tokensDelivered": 100,
                    "tokensAvailable": 400,
                    "savingRatio": 0.75,
                },
            },
        ],
    }

    metrics = communication_metrics(provenance)

    assert metrics["communication_event_count"] == 1
    assert metrics["comm_tokens_delivered_est"] == 100
    assert metrics["comm_tokens_available_est"] == 400
    assert metrics["comm_payload_reduction"] == 0.75


def test_communication_metrics_supports_legacy_consumption_projection() -> None:
    provenance = {
        "integrityStatus": "unknown",
        "legacy": True,
        "consumptions": [
            {"tokensDelivered": 250, "tokensAvailable": 1000, "savingRatio": 0.75}
        ],
    }

    metrics = communication_metrics(provenance)

    assert metrics["communication_event_count"] == 1
    assert metrics["comm_payload_reduction"] == 0.75
