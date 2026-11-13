"""Resolve registered consumption contracts without changing existing frozen steps."""
from __future__ import annotations

from support.acg.capabilities import PlanningCapabilityDescriptor


# These fields carry boundary/evidence information even when not named by the
# consumer's business input schema. Selection never collapses producer identity.
PROTECTED_FIELDS = frozenset({
    "constraints", "acceptance_criteria", "success_criteria", "assumptions",
    "open_questions", "openQuestions", "blockers", "risks", "evidence_refs",
    "evidenceRefs", "sources", "sourceRefs", "verification",
    "source_refs", "unknowns", "unresolvedGaps", "prohibitions", "hard_constraints",
    "acceptanceCriteria", "successCriteria", "risk_analysis",
})


def resolve_prefetch(
    consumer: PlanningCapabilityDescriptor, producer_capability: str, allowed: list[str],
) -> tuple[list[str], str]:
    policy = consumer.context_policy
    if policy is None:
        return list(allowed), "legacy-full-output"
    explicit = policy.prefetch_fields.get(producer_capability)
    required = set(consumer.input_contract.get("required") or [])
    if explicit is not None:
        if not explicit or any(not isinstance(field, str) for field in explicit):
            raise ValueError("prefetch fields must be a nonempty field list")
        if set(explicit) - set(allowed):
            raise ValueError("prefetch fields exceed the producer output contract")
        selected = set(explicit) | (required & set(allowed))
        reason = "registered-fields"
    elif policy.match_input_contract and required.intersection(allowed):
        # Keep optional input properties as well as required business inputs.
        selected = (required | set(consumer.input_contract.get("properties") or {})) & set(allowed)
        reason = "consumer-input-contract"
    else:
        return list(allowed), "ambiguous-full-output"
    selected |= PROTECTED_FIELDS.intersection(allowed)
    return [field for field in allowed if field in selected], reason
