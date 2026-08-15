"""法律 Pack 的技能实现，提供案情、法条、证据、风险和文书相关原子能力。"""


from packs.legal.skills.case_retrieval_skill import CaseRetrievalSkill
from packs.legal.skills.case_understanding_skill import CaseUnderstandingSkill
from packs.legal.skills.document_generation_skill import DocumentGenerationSkill
from packs.legal.skills.evidence_analysis_skill import EvidenceAnalysisSkill
from packs.legal.skills.hearing_outline_generation_skill import HearingOutlineGenerationSkill
from packs.legal.skills.jurisdiction_determination_skill import JurisdictionDeterminationSkill
from packs.legal.skills.limitation_calculation_skill import LimitationCalculationSkill
from packs.legal.skills.risk_assessment_skill import RiskAssessmentSkill
from packs.legal.skills.statute_retrieval_skill import StatuteRetrievalSkill

__all__ = [
    "CaseRetrievalSkill",
    "CaseUnderstandingSkill",
    "DocumentGenerationSkill",
    "EvidenceAnalysisSkill",
    "HearingOutlineGenerationSkill",
    "JurisdictionDeterminationSkill",
    "LimitationCalculationSkill",
    "RiskAssessmentSkill",
    "StatuteRetrievalSkill",
]
