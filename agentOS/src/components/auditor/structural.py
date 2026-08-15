"""结构审计的基础检查。"""


def missing_required_fields(payload: dict[str, object], required: set[str]) -> list[str]:
    """返回 ``payload`` 中缺失的必需字段名，并按字典序稳定排序。

    仅检查键是否存在，不区分空值与非空值，也不执行领域 Schema 校验。集合差集
    与排序的时间复杂度为 O(r log r)，其中 r 为必需字段数，额外空间 O(r)。
    """
    return sorted(required - payload.keys())
