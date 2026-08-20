"""Reference-safe memory events projected from committed node results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from .models import StructuredMemoryEvent


class StructuredMemoryEventBuilder:
    """Build deterministic memory facts without copying prompt or output bodies."""

    @staticmethod
    def build(
        *,
        run_id: str,
        step_id: str,
        commit_id: str,
        summary: str,
        evidence_refs: Iterable[str] = (),
        audit_outcome: str,
        upstream_step_ids: Iterable[str] = (),
        field_count: int = 0,
        model_invocation_count: int = 0,
        tool_call_count: int = 0,
    ) -> StructuredMemoryEvent:
        normalized_evidence = list(
            dict.fromkeys(str(item)[:300] for item in evidence_refs if str(item).strip())
        )
        relations = [
            {"sourceStepId": str(source), "targetStepId": step_id}
            for source in dict.fromkeys(upstream_step_ids)
        ]
        identity = json.dumps(
            {"runId": run_id, "stepId": step_id, "commitId": commit_id},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return StructuredMemoryEvent(
            eventId="memoryevent_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            runId=run_id,
            stepId=step_id,
            commitId=commit_id,
            summary=(str(summary).strip() or f"completed:{step_id}")[:1000],
            evidenceRefs=normalized_evidence,
            metrics={
                "fieldCount": max(0, int(field_count)),
                "evidenceCount": len(normalized_evidence),
                "modelInvocationCount": max(0, int(model_invocation_count)),
                "toolCallCount": max(0, int(tool_call_count)),
            },
            decision=str(audit_outcome),
            relations=relations,
        )


__all__ = ["StructuredMemoryEventBuilder"]
