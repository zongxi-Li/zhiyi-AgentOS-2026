"""模板匹配器。

“静态优选”：以 role_type(domain) + task_type(intent) 为一级索引筛候选，
再用轻量语义相似度对 description/tags 打分，命中阈值（默认 0.85）则复用
经过验证的高质量模板，省去动态规划开销，输出质量有预期保障。

相似度本阶段用字符级 n-gram + 关键词重合的混合启发式（无外部向量依赖）。
预留 embed 钩子，后续可注入向量模型平滑升级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .models import TaskSemanticProfile
from task_manager.store import WorkflowRegistry

# 工作流对象由任务管理器提供；规划器只读取其公开字段。
WorkflowDefinition = Any


@dataclass
class TemplateMatch:
    """模板检索结果；``score`` 在 0 到 1 间，``matched_by`` 说明候选来源。"""
    workflow: WorkflowDefinition
    score: float
    matched_by: str  # "index+similarity" / "index" / "none"


def _char_bigrams(text: str) -> set[str]:
    text = "".join((text or "").lower().split())
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _dice_similarity(a: str, b: str) -> float:
    ba, bb = _char_bigrams(a), _char_bigrams(b)
    if not ba or not bb:
        return 0.0
    inter = len(ba & bb)
    return 2.0 * inter / (len(ba) + len(bb))


class TemplateMatcher:
    """工作流模板匹配。"""

    def __init__(self, registry: WorkflowRegistry, *, threshold: float = 0.85):
        self.registry = registry
        self.threshold = threshold

    def match(self, profile: TaskSemanticProfile) -> TemplateMatch:
        """按领域筛选模板并选择相似度最高者。

        精确意图候选优先，否则比较同领域模板；遍历顺序稳定，复杂度约为候选数乘文本长度，
        不修改注册表或画像。
        """
        domain = profile.domain_hint.strip().lower()
        intent = profile.task_type_hint.strip().lower()

        # 一级索引：domain + intent 精确命中
        candidates: List[WorkflowDefinition] = []
        for wf in self.registry.all():
            if wf.domain.lower() == domain and not wf.is_native_bootstrap:
                candidates.append(wf)

        if not candidates:
            return TemplateMatch(workflow=None, score=0.0, matched_by="none")  # type: ignore[arg-type]

        # intent 是一级索引信号，但不能绕过语义与能力检查直接保送。
        exact = [wf for wf in candidates if wf.intent.lower() == intent]
        if exact:
            scored = [(self._similarity(profile, wf, exact_intent=True), wf) for wf in exact]
            score, wf = max(scored, key=lambda item: item[0])
            return TemplateMatch(workflow=wf, score=round(score, 4), matched_by="index+similarity")

        # 否则在同域候选里按相似度选最优
        best: Optional[WorkflowDefinition] = None
        best_score = 0.0
        for wf in candidates:
            sim = self._similarity(profile, wf, exact_intent=False)
            if sim > best_score:
                best, best_score = wf, sim

        matched_by = "index+similarity" if best_score >= self.threshold else "index"
        return TemplateMatch(workflow=best, score=round(best_score, 4), matched_by=matched_by)

    def is_hit(self, match: TemplateMatch) -> bool:
        """判断结果是否含模板且分数达到当前阈值，不重新计算相似度。"""
        return match.workflow is not None and match.score >= self.threshold

    def _similarity(
        self, profile: TaskSemanticProfile, wf: WorkflowDefinition, *, exact_intent: bool
    ) -> float:
        query = f"{profile.primary_goal} {profile.raw_intent} {' '.join(profile.required_capabilities)}"
        target = f"{wf.name} {wf.description} {wf.intent} {' '.join(wf.tags)}"
        text_score = _dice_similarity(query, target)
        cap_hits = sum(1 for cap in profile.required_capabilities if cap and cap in target)
        capability_score = cap_hits / len(profile.required_capabilities) if profile.required_capabilities else 0.0
        if exact_intent:
            return min(1.0, 0.84 + 0.10 * text_score + 0.06 * capability_score)
        return min(1.0, 0.7 * text_score + 0.3 * capability_score)


__all__ = ["TemplateMatcher", "TemplateMatch"]
