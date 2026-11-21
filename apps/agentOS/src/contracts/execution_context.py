"""Project an already admitted node input across heterogeneous Agent adapters.

The projection performs no retrieval and exposes no Runtime, store or tool
objects. The communicator and memory service remain the input authorities.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from contracts.execution_guidance import guidance_projection


def project_execution_context(context: Any) -> dict[str, Any]:
    """Copy the authorized input and this execution's frozen memory records."""
    pack = getattr(context, "context_pack", None)
    memory = [
        record.model_dump(by_alias=True, mode="json")
        if hasattr(record, "model_dump") else record
        for record in (getattr(context, "memory", None) or [])
    ]
    delivered = {
        "data": dict(getattr(pack, "data", {}) or {}),
        "sourceData": dict(getattr(pack, "source_data", {}) or {}),
        "evidenceRefs": list(getattr(pack, "evidence_refs", []) or []),
        "memory": memory,
    }
    guidance = guidance_projection(context)
    if guidance:
        delivered["executionGuidance"] = guidance
    return deepcopy(delivered)


def execution_attempt_id(context: Any) -> str:
    """Prefer the scheduler identity over legacy ContextPack/commit fallbacks."""
    pack = getattr(context, "context_pack", None)
    return str(getattr(context, "attempt_id", None)
               or getattr(pack, "attempt_id", None)
               or getattr(context, "commit_id", None) or "")


def has_retry_evidence(context: Any) -> bool:
    """Use the recovery protocol frozen when this new Attempt was admitted."""
    state = context.run.execution_state
    proofs = list((state.get("settledSessionRetryProofs") or {}).values())
    if state.get("retryEvidenceContextVersion") == 1:
        proofs.extend((state.get("readOnlyRetryProofs") or {}).values())
    return any(isinstance(proof, dict) and proof.get("stepId") == context.step.step_id for proof in proofs)


__all__ = ["execution_attempt_id", "project_execution_context", "has_retry_evidence"]
