"""Planning capability contribution owned by the Education Pack."""

from support.acg.models import CapabilityCatalog, PlanningCapabilityDescriptor


def register_education_capabilities(catalog: CapabilityCatalog) -> None:
    try:
        catalog.get("lesson_plan")
        return
    except KeyError:
        pass
    descriptor = PlanningCapabilityDescriptor(
        capabilityId="lesson_plan",
        displayName="Lesson plan design",
        aliases=["teaching_design", "lesson planning"],
        planningStage="deliver",
        outputContract={"type": "object", "required": ["lesson_plan", "final_answer"]},
        producesArtifact=True,
        writesMemory=True,
        domainHints=["education"],
        priority=30,
    )
    candidate = CapabilityCatalog([*catalog.available(), descriptor])
    candidate.validate()
    catalog.register(descriptor)
    catalog.validate()


__all__ = ["register_education_capabilities"]
