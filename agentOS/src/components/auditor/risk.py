"""风险等级归一化。"""


def classify_risk(score: float) -> str:
    """把量化审计分数映射为合同允许的风险等级字符串。

    分界值依次为 critical(15)、high(7)、medium(3)；正的较低分为 low，非正
    分为 info。函数不截断输入也不访问策略存储，时间与空间复杂度均为 O(1)。
    """
    if score >= 15:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 3:
        return "medium"
    return "low" if score > 0 else "info"
