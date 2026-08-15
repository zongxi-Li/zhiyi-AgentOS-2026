"""Legal recovery agents used by Core's domain-neutral ACG recipes."""

from __future__ import annotations

import hashlib
from typing import Any

from app.execution.tool_calls import network_tools_enabled
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from app.execution.tool_calls import execute_read_only_tool
from app.rag.legal_evidence_schema import normalize_evidence


def _observation_values(context) -> list[dict[str, Any]]:
    return [
        value
        for value in context.memory.observations.values()
        if isinstance(value, dict)
    ]


def _latest_field(context, field: str) -> Any:
    for value in reversed(_observation_values(context)):
        if field in value:
            return value[field]
    return None


class LegalEvidenceRecoveryAgent(BaseAgent):
    """Recover unmatched risks from one bounded public-web search with safe fallback."""

    def __init__(self) -> None:
        super().__init__(
            AgentProfile(
                agentName="legal_evidence_recovery",
                domain="legal",
                capabilities=["evidence_retrieval"],
                allowedTools=["web_search", "current_datetime"],
                description="Recovers missing legal evidence from bounded public-web search.",
            )
        )

    async def run(self, context) -> AgentOutput:
        observations = _observation_values(context)
        risk_output = next(
            (item for item in reversed(observations) if isinstance(item.get("risks"), list)),
            {},
        )
        match_output = next(
            (item for item in reversed(observations) if isinstance(item.get("retrieval"), dict)),
            {},
        )
        unmatched = {
            str(value)
            for value in (match_output.get("retrieval", {}).get("unmatched_risk_ids") or [])
            if str(value)
        }
        risks = [
            item
            for item in (risk_output.get("risks") or [])
            if isinstance(item, dict) and (not unmatched or str(item.get("id") or "") in unmatched)
        ]
        contract_text = str(
            context.task.input.get("contractText")
            or context.task.input.get("caseText")
            or context.task.input.get("text")
            or context.task.input.get("userIntent")
            or context.task.title
        ).strip()
        web = None
        if risks and network_tools_enabled(context.task.input):
            jurisdiction = str(
                context.task.input.get("jurisdiction")
                or context.task.input.get("governingLaw")
                or "中国"
            ).strip()
            risk_terms = "；".join(
                str(item.get("title") or item.get("clause") or item.get("id") or "")
                for item in risks
            )
            query = f"{jurisdiction} 合同审查 法律依据 司法解释 {risk_terms}"[:500]
            web = await execute_read_only_tool(
                context.tool_runtime,
                "web_search",
                {"query": query, "max_results": 5, "topic": "general"},
            )
        result_by_citation = {
            str(item.get("citationId")): item
            for item in (web.results if web is not None else [])
            if item.get("citationId")
        }
        web_sources = web.sources if web is not None and web.ok else []
        recovered: list[dict[str, Any]] = []
        for index, risk in enumerate(risks, start=1):
            risk_id = str(risk.get("id") or f"risk-{index:02d}")
            if web_sources:
                source = web_sources[(index - 1) % len(web_sources)]
                citation_id = str(source.get("citationId") or "")
                row = result_by_citation.get(citation_id, {})
                url = str(source.get("url") or row.get("url") or "")
                title = str(source.get("title") or row.get("title") or url)
                snippet = str(
                    source.get("snippet")
                    or row.get("snippet")
                    or row.get("content")
                    or ""
                ).strip()
                digest = hashlib.sha256(
                    f"{context.run.run_id}:{risk_id}:{citation_id}".encode("utf-8")
                ).hexdigest()[:12]
                recovered.append(
                    normalize_evidence(
                        {
                            "id": f"web-{digest}",
                            "riskId": risk_id,
                            "stepId": context.step.step_id,
                            "sourceType": "web",
                            "sourceName": title or "Public web source",
                            "title": title or str(risk.get("title") or "Legal source"),
                            "content": snippet[:2000],
                            "citationText": f"[{title}]({url})" if url else title,
                            "confidence": 0.55,
                            "retrievalScore": float(row.get("score") or 0.0),
                            "metadata": {
                                "citationId": citation_id,
                                "url": url,
                                "provider": source.get("provider"),
                                "retrievedAt": source.get("retrievedAt"),
                                "requiresLegalVerification": True,
                                "authoritativeSourceMissing": False,
                            },
                        },
                        risk_id=risk_id,
                    )
                )
                continue
            digest = hashlib.sha256(
                f"{context.run.run_id}:{risk_id}:task-fact".encode("utf-8")
            ).hexdigest()[:12]
            recovered.append(
                normalize_evidence(
                    {
                        "id": f"recovered-{digest}",
                        "riskId": risk_id,
                        "stepId": context.step.step_id,
                        "sourceType": "task-input",
                        "sourceName": "User-provided contract facts",
                        "title": str(risk.get("title") or "Unmatched contract risk"),
                        "content": contract_text[:2000],
                        "citationText": "用户提供的合同事实；尚待权威法律依据复核",
                        "confidence": 0.25,
                        "retrievalScore": 0.0,
                        "metadata": {
                            "provisional": True,
                            "authoritativeSourceMissing": True,
                        },
                    },
                    risk_id=risk_id,
                )
            )
        return AgentOutput(
            output={
                "recovered_evidences": recovered,
                "recovery_status": "recovered" if recovered else "nothing_to_recover",
                "recovery_mode": "web_search" if web_sources else "task_input",
                "retrieval_error": web.error_code if web is not None else None,
            },
            summary=f"Recovered {len(recovered)} provenance-marked legal evidence item(s).",
            sources=web_sources,
            toolExecutions=web.executions if web is not None else [],
            evidenceRefs=[
                str(item.get("citationId"))
                for item in web_sources
                if item.get("citationId")
            ],
        )


class LegalEvidenceValidationAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            AgentProfile(
                agentName="legal_evidence_validation",
                domain="legal",
                capabilities=["evidence_validation"],
                description="Validates and deduplicates recovered legal evidence.",
            )
        )

    async def run(self, context) -> AgentOutput:
        candidates = _latest_field(context, "recovered_evidences") or []
        validated: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            normalized = normalize_evidence(item)
            key = (normalized["riskId"], normalized["id"])
            if not normalized["riskId"] or not normalized["content"] or key in seen:
                continue
            seen.add(key)
            validated.append(normalized)
        return AgentOutput(
            output={
                "validated_evidences": validated,
                "validation_status": "valid" if validated else "empty",
            },
            summary=f"Validated {len(validated)} recovered legal evidence item(s).",
        )


class LegalContractAdapterAgent(BaseAgent):
    """Expose the Core contract-repair capability for the legal domain."""

    def __init__(self) -> None:
        super().__init__(
            AgentProfile(
                agentName="legal_contract_adapter",
                domain="legal",
                capabilities=["contract_adapter"],
                description="Normalizes the latest legal step payload for a bounded retry.",
            )
        )

    async def run(self, context) -> AgentOutput:
        raise RuntimeError(
            "CONTRACT_REPAIR_MIGRATION_PENDING: the C4 repair algorithm must be "
            "reimplemented in components.recovery before this binding is enabled"
        )


__all__ = [
    "LegalContractAdapterAgent",
    "LegalEvidenceRecoveryAgent",
    "LegalEvidenceValidationAgent",
]
