"""Planning capability contribution owned by the Writer Pack."""

from support.acg.models import CapabilityCatalog, PlanningCapabilityDescriptor


def register_writer_capabilities(catalog: CapabilityCatalog) -> None:
    try:
        catalog.get("outline_generate")
        return
    except KeyError:
        pass
    descriptor = PlanningCapabilityDescriptor(
        capabilityId="outline_generate",
        displayName="Story outline generation",
        aliases=["story_outline", "outline generation"],
        planningStage="deliver",
        outputContract={"type": "object", "required": ["outline", "outline_markdown", "final_answer"]},
        producesArtifact=True,
        writesMemory=True,
        domainHints=["writer"],
        priority=30,
    )
    candidate = CapabilityCatalog([*catalog.available(), descriptor])
    candidate.validate()
    catalog.register(descriptor)
    catalog.validate()


__all__ = ["register_writer_capabilities"]
