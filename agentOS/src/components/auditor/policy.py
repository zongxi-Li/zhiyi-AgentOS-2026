"""政策决定的局部规则。"""


def policy_outcome(has_critical_finding: bool, requires_human_review: bool = False) -> str:
    """按固定优先级给出 ``deny``、``review`` 或 ``allow`` 决策。

    严重发现始终覆盖人工复核标记而返回 ``deny``；没有严重发现时才依据
    ``requires_human_review`` 决定是否复核。函数不读取外部策略，时间与空间
    复杂度均为 O(1)。
    """
    return "deny" if has_critical_finding else "review" if requires_human_review else "allow"
