"""通信内容选择的纯函数。"""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import estimate_tokens


def field_value(field_name: str, value: Any) -> float:
    """计算字段投递价值：证据、结论和短字段优先，规则完全确定性。"""
    name = field_name.lower()
    semantic_bonus = 4.0 if any(key in name for key in ("evidence", "answer", "result", "decision")) else 1.0
    if value in (None, "", [], {}):
        return 0.0
    return semantic_bonus


def select_fields(payload: Mapping[str, Any], allowed_fields: list[str], token_budget: int | None = None) -> list[str]:
    """在白名单内按价值/Token 降序选择；同分以字段名排序保证可重放。"""
    budget = token_budget if token_budget is not None else 2**31 - 1
    candidates = []
    for name in dict.fromkeys(str(item) for item in allowed_fields):
        if name in payload:
            tokens = max(1, estimate_tokens(payload[name]))
            candidates.append((-(field_value(name, payload[name]) / tokens), name, tokens))
    selected: list[str] = []
    used = 0
    for _, name, tokens in sorted(candidates):
        if used + tokens <= budget:
            selected.append(name)
            used += tokens
    return selected


def low_entropy_choice(candidates: list[str], payload: Mapping[str, Any] | None = None, token_budget: int | None = None) -> str | None:
    """返回价值/Token 最优字段，取代过去仅按字典序选择的低熵策略。"""
    data = payload or {candidate: candidate for candidate in candidates}
    selected = select_fields(data, candidates, token_budget)
    return selected[0] if selected else None
