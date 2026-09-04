"""证据引用检查。"""


def evidence_complete(evidence_refs: list[str]) -> bool:
    """判断证据引用列表是否至少含有一个非空标识。

    输入中的空白字符串不计为证据，返回 ``True`` 仅表示存在可追踪引用，并不
    验证引用是否真实可访问。算法短路扫描，时间复杂度 O(n)、额外空间 O(1)。
    """
    return any(ref.strip() for ref in evidence_refs)
