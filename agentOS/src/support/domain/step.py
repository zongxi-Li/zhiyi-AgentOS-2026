"""运行时配套的工作流步骤领域模型，不承担跨部件业务实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _normalize_identifier(value: str | None, *, field_name: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    return normalized or None


@dataclass
class StepDefinition:
    """线性工作流的步骤声明。

    步骤与智能体标识必须非空且规范化；输入复制为独立字典，重试次数必须非负，后继标识
    为空表示由工作流顺序决定或流程结束。
    """
    step_id: str
    name: str
    agent_name: str
    capability: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    review_required: bool = False
    next_step_id: str | None = None
    max_retries: int = 0

    def __post_init__(self) -> None:
        self.step_id = _normalize_identifier(self.step_id, field_name="step_id")
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValueError("name is required")
        self.agent_name = _normalize_identifier(self.agent_name, field_name="agent_name")
        self.capability = _normalize_optional_text(self.capability)
        self.input = dict(self.input or {})
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.max_retries = int(self.max_retries)
        self.next_step_id = _normalize_optional_text(self.next_step_id)
