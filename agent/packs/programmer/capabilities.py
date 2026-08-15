"""Planning capability contribution owned by the Programmer Pack."""

from support.acg.models import CapabilityCatalog, PlanningCapabilityDescriptor


def programmer_capabilities() -> tuple[PlanningCapabilityDescriptor, ...]:
    return (
        PlanningCapabilityDescriptor(
            capabilityId="codebase_semantic_search",
            displayName="Codebase semantic search",
            aliases=["code search", "repository search"],
            planningStage="research",
            dependsOn=["requirement_analysis"],
            outputContract={"type": "object", "required": ["hits", "evidence_refs"]},
            requiresEvidence=True,
            writesMemory=True,
            domainHints=["programmer"],
            priority=30,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="code_generation",
            displayName="Code generation",
            planningStage="produce",
            dependsOn=["codebase_semantic_search"],
            outputContract={"type": "object", "required": ["code", "suggested_tests"]},
            producesArtifact=True,
            writesMemory=True,
            riskLevelHint="elevated",
            domainHints=["programmer"],
            priority=40,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="diagram_generation",
            displayName="Architecture diagram generation",
            planningStage="deliver",
            dependsOn=["code_generation"],
            outputContract={"type": "object", "required": ["mermaid_code"]},
            producesArtifact=True,
            writesMemory=True,
            domainHints=["programmer"],
            priority=50,
        ),
    )


def register_programmer_capabilities(catalog: CapabilityCatalog) -> None:
    descriptors = programmer_capabilities()
    if all(any(item.capability_id == descriptor.capability_id for item in catalog.available()) for descriptor in descriptors):
        return
    candidate = CapabilityCatalog([*catalog.available(), *descriptors])
    candidate.validate()
    for descriptor in descriptors:
        catalog.register(descriptor)
    catalog.validate()


__all__ = ["programmer_capabilities", "register_programmer_capabilities"]
