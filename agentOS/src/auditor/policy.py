"""政策决定的局部规则。"""


def policy_outcome(has_critical_finding: bool, requires_human_review: bool = False) -> str:
    """严重发现拒绝，显式人工复核次之，其余允许。"""
    return "deny" if has_critical_finding else "review" if requires_human_review else "allow"
