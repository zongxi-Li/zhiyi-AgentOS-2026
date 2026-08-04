"""结构审计的基础检查。"""


def missing_required_fields(payload: dict[str, object], required: set[str]) -> list[str]:
    """返回未出现的必需字段，避免与具体领域模型耦合。"""
    return sorted(required - payload.keys())
