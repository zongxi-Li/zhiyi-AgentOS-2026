"""运行时配套的通用智能体领域模型，不承担跨部件业务实现。"""

from __future__ import annotations

from dataclasses import dataclass, field


def _normalize_text(value: str | None, *, field_name: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _normalize_terms(values: list[str] | tuple[str, ...] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = (value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


@dataclass
class AgentProfile:
    """轻量智能体画像。

    初始化时规范化名称、领域和权限词表为去重小写值；空名称或领域抛出 ``ValueError``，
    能力与权限判断均基于该规范化不变量。
    """
    agent_name: str
    domain: str
    capabilities: list[str] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    risk_level: str = "normal"
    description: str = ""

    def __post_init__(self) -> None:
        self.agent_name = _normalize_text(self.agent_name, field_name="agent_name")
        self.domain = _normalize_text(self.domain, field_name="domain")
        self.capabilities = _normalize_terms(self.capabilities)
        self.allowed_skills = _normalize_terms(self.allowed_skills)
        self.allowed_tools = _normalize_terms(self.allowed_tools)
        self.risk_level = (self.risk_level or "normal").strip().lower() or "normal"
        self.description = (self.description or "").strip()

    def supports(self, capability: str) -> bool:
        """判断规范化能力是否被声明支持；空输入返回 ``False``，时间复杂度 ``O(C)``。"""
        normalized = (capability or "").strip().lower()
        return bool(normalized) and normalized in self.capabilities

    def can_use_skill(self, skill_name: str) -> bool:
        """判断技能是否在白名单内；空输入返回 ``False``，不修改权限集合。"""
        normalized = (skill_name or "").strip().lower()
        return bool(normalized) and normalized in self.allowed_skills

    def can_use_tool(self, tool_name: str) -> bool:
        """判断工具是否在白名单内；空输入返回 ``False``，不修改权限集合。"""
        normalized = (tool_name or "").strip().lower()
        return bool(normalized) and normalized in self.allowed_tools
