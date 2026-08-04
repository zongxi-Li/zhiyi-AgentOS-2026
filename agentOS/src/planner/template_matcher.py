"""计划模板的轻量匹配接口。"""


def match_template(keywords: list[str], templates: dict[str, set[str]]) -> str | None:
    """返回关键词交集最大的模板；无交集时保持无模板状态。"""
    requested = set(keywords)
    candidates = [(len(requested & terms), name) for name, terms in templates.items()]
    score, name = max(candidates, default=(0, ""))
    return name if score else None
