"""写作 Pack 的技能实现，提供灵感扩展、大纲、人物关系和正文写作能力。"""


import asyncio
import logging
from typing import Any, Dict

from contracts.workflow import SkillRequest, SkillResult
from support.skills.base import BaseSkill
from packs.writer.skills.common import WriterSkillHelper
from adapters.model_adapter import AIService

logger = logging.getLogger(__name__)


class InspirationExpandSkill(BaseSkill):
    def __init__(self, ai_service: AIService = None):
        super().__init__("inspiration_expand")
        self.ai_service = ai_service or AIService()

    def _fallback_output(self, premise: str, reason: str) -> Dict[str, Any]:
        return {
            "premise": premise,
            "creative_tree": WriterSkillHelper.default_creative_tree(premise),
            "fallback_reason": reason,
        }

    async def execute(self, request: SkillRequest) -> SkillResult:
        action_input = request.action_input or {}
        premise = str(action_input.get("premise", request.text or "")).strip() or "故事创意"

        prompt = WriterSkillHelper.load_prompt(
            "inspiration_expand.txt",
            (
                "你是一名创意写作助手，请始终使用简体中文（JSON 键名保持原样）。\n"
                "给定前提：{premise}\n"
                "请仅返回严格 JSON，顶层键为 creative_tree。\n"
                "creative_tree 必须包含 id、label、description、children。\n"
            ),
        ).replace("{premise}", premise)

        llm_json: Dict[str, Any] = {}
        try:
            llm_response = await self.ai_service.generate_text(
                text=prompt,
                context=request.memory.get("history", [])[-6:],
            )
            llm_json = WriterSkillHelper.extract_json_obj(llm_response.get("text", ""))
        except Exception as exc:
            logger.warning("InspirationExpandSkill LLM call failed: %s", exc)

        if llm_json:
            tree = WriterSkillHelper.normalize_creative_tree(llm_json, premise=premise)
            output = {"premise": premise, "creative_tree": tree}
        else:
            output = self._fallback_output(premise=premise, reason="llm_unavailable")

        return SkillResult(
            skillName=self.name,
            success=True,
            output=output,
            message="灵感扩展完成。",
        )

    async def run(self, request: SkillRequest) -> SkillResult:
        action_input = request.action_input or {}
        premise = str(action_input.get("premise", request.text or "")).strip() or "故事创意"
        try:
            return await asyncio.wait_for(self.execute(request), timeout=45)
        except asyncio.TimeoutError:
            return SkillResult(
                skillName=self.name,
                success=True,
                output=self._fallback_output(premise=premise, reason="timeout"),
                message="灵感扩展超时，已返回降级结果。",
            )
        except Exception as exc:
            logger.error("InspirationExpandSkill failed: %s", exc, exc_info=True)
            return SkillResult(
                skillName=self.name,
                success=True,
                output=self._fallback_output(premise=premise, reason="error"),
                message="灵感扩展执行异常，已返回降级结果。",
            )
