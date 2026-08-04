"""Domain model for a workflow definition."""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.step import StepDefinition, _normalize_identifier


def _normalize_optional_text(value: str | None) -> str:
    return (value or "").strip().lower()


@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    domain: str
    intent: str = "general"
    version: str = "1.0.0"
    description: str = ""
    steps: list[StepDefinition] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workflow_id = _normalize_identifier(self.workflow_id, field_name="workflow_id")
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValueError("name is required")
        self.domain = _normalize_identifier(self.domain, field_name="domain")
        self.intent = _normalize_optional_text(self.intent) or "general"
        self.version = (self.version or "1.0.0").strip() or "1.0.0"
        self.description = (self.description or "").strip()
        self.steps = [step if isinstance(step, StepDefinition) else StepDefinition(**step) for step in self.steps]
        if not self.steps:
            raise ValueError(f"workflow {self.workflow_id} must define at least one step")
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError(f"duplicate step_id in workflow {self.workflow_id}: {step.step_id}")
            seen.add(step.step_id)

    def first_step_id(self) -> str | None:
        return self.steps[0].step_id if self.steps else None

    def get_step(self, step_id: str) -> StepDefinition:
        normalized = _normalize_identifier(step_id, field_name="step_id")
        for step in self.steps:
            if step.step_id == normalized:
                return step
        raise KeyError(f"workflow step not found: {step_id}")

    def next_step_id(self, step_id: str) -> str | None:
        definition = self.get_step(step_id)
        if definition.next_step_id in {"", "done", "completed", None}:
            if definition.next_step_id in {"done", "completed"}:
                return None
        if definition.next_step_id:
            return definition.next_step_id

        for index, step in enumerate(self.steps):
            if step.step_id == definition.step_id:
                next_index = index + 1
                return self.steps[next_index].step_id if next_index < len(self.steps) else None
        return None
