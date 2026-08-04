"""AgentOS Core 的技能基础接口，定义 BaseSkill 和 NoOpSkill。"""


from __future__ import annotations

from abc import ABC, abstractmethod

from contracts.workflow import SkillRequest, SkillResult


class BaseSkill(ABC):
    """可复用技能的统一接口。"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def run(self, request: SkillRequest) -> SkillResult:
        raise NotImplementedError


class NoOpSkill(BaseSkill):
    """测试和空注册表使用的兜底技能。"""

    def __init__(self, name: str = "noop"):
        super().__init__(name)

    async def run(self, request: SkillRequest) -> SkillResult:
        return SkillResult(
            skillName=self.name,
            success=True,
            output={
                "text": request.text,
                "action_input": request.action_input,
            },
            message="NoOpSkill completed.",
        )
