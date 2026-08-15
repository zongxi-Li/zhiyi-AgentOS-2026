"""Lower-priority compatible binding for the canonical legal workflow."""

from __future__ import annotations

from service.agents.base import AgentProfile, BaseAgent
from packs.legal.agents.contract_review_migration import (
    ClauseClassifyAgent,
    ContractParseAgent,
    HumanReviewGateAgent,
    LegalEvidenceMatchAgent,
    ReportGenerateAgent,
    RevisionSuggestAgent,
    RiskDetectAgent,
)
from packs.legal.planning.capabilities import LEGAL_CAPABILITY_RUNTIME_IDS


class LegalWorkflowFallbackAgent(BaseAgent):
    """Route a retried legal step through a fresh, lower-priority agent binding."""

    def __init__(self) -> None:
        runtime_delegates = {
            "contract_parse": ContractParseAgent(),
            "clause_classify": ClauseClassifyAgent(),
            "risk_detect": RiskDetectAgent(),
            "legal_evidence_match": LegalEvidenceMatchAgent(),
            "revision_suggest": RevisionSuggestAgent(),
            "human_review_gate": HumanReviewGateAgent(),
            "report_generate": ReportGenerateAgent(),
        }
        self._delegates = {
            **runtime_delegates,
            **{
                stable_id: runtime_delegates[runtime_id]
                for stable_id, runtime_id in LEGAL_CAPABILITY_RUNTIME_IDS.items()
            },
        }
        allowed_skills = sorted(
            {
                skill
                for delegate in runtime_delegates.values()
                for skill in delegate.profile.allowed_skills
            }
        )
        super().__init__(
            AgentProfile(
                agentName="legal_workflow_fallback",
                domain="legal",
                capabilities=list(self._delegates),
                allowedSkills=allowed_skills,
                bindingPriority=-100,
                description="Fallback binding for canonical legal contract-review steps.",
            )
        )

    async def run(self, context):
        capability = str(context.step.capability or "")
        delegate = self._delegates.get(capability)
        if delegate is None:
            raise KeyError(f"unsupported legal fallback capability: {capability}")
        return await delegate.run(context)


__all__ = ["LegalWorkflowFallbackAgent"]
