"""证据引用检查。"""


def evidence_complete(evidence_refs: list[str]) -> bool:
    """至少包含一条非空证据引用才认为证据链可追踪。"""
    return any(ref.strip() for ref in evidence_refs)
