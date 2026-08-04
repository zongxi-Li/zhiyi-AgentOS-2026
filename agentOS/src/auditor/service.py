"""审计部件的公共 Facade。"""

from .algorithms import audit_score
from .risk import classify_risk


class AuditorService:
    """汇总发现等级并输出可读审计摘要。"""

    def assess(self, severity_counts: dict[str, int]) -> dict[str, object]:
        """不访问外部证据库，仅计算本地汇总评分。"""
        score = audit_score(severity_counts)
        return {"score": score, "severity": classify_risk(score)}

    # TODO: 接入证据存储和策略引擎后，验证引用存在性与组织级规则。
