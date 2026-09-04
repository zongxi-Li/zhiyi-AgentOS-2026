"""通信内容选择的纯函数。"""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import estimate_tokens


def field_value(field_name: str, value: Any) -> float:
    """按字段语义计算确定性的投递价值。

    空值返回零，名称含证据、答案、结果或决策关键词的非空字段获得更高权重；
    不读取内容或模型评分。计算仅扫描固定关键词，时间与空间复杂度均为 O(1)。
    """
    name = field_name.lower()
    semantic_bonus = 4.0 if any(key in name for key in ("evidence", "answer", "result", "decision")) else 1.0
    if value in (None, "", [], {}):
        return 0.0
    return semantic_bonus


def select_fields(payload: Mapping[str, Any], allowed_fields: list[str], token_budget: int | None = None) -> list[str]:
    """在字段白名单内按价值密度选择不超过 Token 预算的字段。

    重复白名单项被去重，候选按价值/Token 降序和名称升序稳定排序；返回所选字段
    名而不修改 ``payload``。设候选数为 n，复杂度为 O(n log n) 时间、O(n) 空间。
    """
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
    """从候选字段中返回价值密度最高且满足预算的一项。

    未提供 ``payload`` 时以字段名自身作为值；没有可选字段时返回 ``None``。
    排序策略复用 :func:`select_fields`，时间复杂度 O(n log n)、额外空间 O(n)。
    """
    data = payload or {candidate: candidate for candidate in candidates}
    selected = select_fields(data, candidates, token_budget)
    return selected[0] if selected else None
