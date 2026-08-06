"""运行时配套的线性工作流领域模型，不承担跨部件业务实现。"""

from __future__ import annotations

from dataclasses import dataclass, field

from support.domain.step import StepDefinition, _normalize_identifier


def _normalize_optional_text(value: str | None) -> str:
    return (value or "").strip().lower()


@dataclass
class WorkflowDefinition:
    """线性工作流定义。

    工作流、领域、名称与至少一个步骤为必需不变量；步骤标识在同一工作流内必须唯一，
    违反时初始化抛出 ``ValueError``。
    """
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
        """返回声明顺序中第一个步骤标识；兼容空列表时返回 ``None``。"""
        return self.steps[0].step_id if self.steps else None

    def get_step(self, step_id: str) -> StepDefinition:
        """按规范化标识线性查找步骤，复杂度 ``O(S)``；缺失时抛出 ``KeyError``。"""
        normalized = _normalize_identifier(step_id, field_name="step_id")
        for step in self.steps:
            if step.step_id == normalized:
                return step
        raise KeyError(f"workflow step not found: {step_id}")

    def next_step_id(self, step_id: str) -> str | None:
        """返回显式后继或声明顺序后继；``done``/``completed`` 与末步骤均返回 ``None``。"""
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
