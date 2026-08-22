"""法律 Pack 的注册入口与包级配置。"""


from pathlib import Path

from components.mission_manager.store import WorkflowRegistry
from packs.legal.agents.case_intake import CaseIntakeAgent
from packs.legal.agents.contract_review_migration import (
    ClauseClassifyAgent,
    ContractFinalReviewAgent,
    ContractParseAgent,
    HumanReviewGateAgent,
    LegalEvidenceMatchAgent,
    ReportGenerateAgent,
    RevisionSuggestAgent,
    RiskDetectAgent,
)
from packs.legal.agents.draft import DraftAgent
from packs.legal.agents.evidence import EvidenceAgent
from packs.legal.agents.fallback import LegalWorkflowFallbackAgent
from packs.legal.agents.review import ReviewAgent
from packs.legal.agents.risk import RiskAgent
from packs.legal.agents.recovery import (
    LegalContractAdapterAgent,
    LegalEvidenceRecoveryAgent,
    LegalEvidenceValidationAgent,
)
from packs.legal.agents.statute import StatuteAgent
from packs.legal.planning import (
    LEGAL_CAPABILITY_AGENT_NAMES,
    LEGAL_CAPABILITY_RUNTIME_IDS,
    LEGAL_PLUGIN_ID,
    LEGAL_PLUGIN_VERSION,
    register_legal_capabilities,
)


def register_pack(
    agent_registry,
    workflow_registry,
    capability_catalog,
    manifest=None,
) -> None:
    """注册法律示例 Pack，并保持 Core 与法律业务逻辑解耦。"""

    agents = [
        CaseIntakeAgent(),
        StatuteAgent(),
        EvidenceAgent(),
        RiskAgent(),
        DraftAgent(),
        ReviewAgent(),
        ContractParseAgent(),
        ClauseClassifyAgent(),
        RiskDetectAgent(),
        LegalEvidenceMatchAgent(),
        RevisionSuggestAgent(),
        HumanReviewGateAgent(),
        ReportGenerateAgent(),
        ContractFinalReviewAgent(),
        LegalEvidenceRecoveryAgent(),
        LegalEvidenceValidationAgent(),
        LegalContractAdapterAgent(),
        LegalWorkflowFallbackAgent(),
    ]
    plugin_id = manifest.pack_id if manifest is not None else LEGAL_PLUGIN_ID
    plugin_version = manifest.version if manifest is not None else LEGAL_PLUGIN_VERSION
    for agent in agents:
        capabilities = list(agent.profile.capabilities)
        for stable_id, runtime_id in LEGAL_CAPABILITY_RUNTIME_IDS.items():
            if (
                agent.profile.agent_name == LEGAL_CAPABILITY_AGENT_NAMES[stable_id]
                and runtime_id in capabilities
                and stable_id not in capabilities
            ):
                capabilities.append(stable_id)
        agent.profile = agent.profile.model_copy(
            update={
                "capabilities": capabilities,
                "source": "plugin",
                "plugin_id": plugin_id,
                "plugin_version": plugin_version,
                "contribution_id": agent.profile.agent_name,
            }
        )

    workflows = WorkflowRegistry()
    workflows.load_directory(Path(__file__).resolve().parent / "workflows")

    register_legal_capabilities(capability_catalog)
    for agent in agents:
        agent_registry.register(agent)
    for workflow in workflows.all():
        workflow_registry.register(
            workflow.model_copy(
                update={
                    "source": "plugin",
                    "plugin_id": plugin_id,
                    "plugin_version": plugin_version,
                    "contribution_id": workflow.workflow_id,
                }
            )
        )
