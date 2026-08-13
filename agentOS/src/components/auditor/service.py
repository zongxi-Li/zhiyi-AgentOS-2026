"""审计部件的公共 Facade。"""

from .algorithms import audit_score
from .execution_audit import ExecutionAuditService
from .risk import classify_risk


class AuditorService:
    """汇总本地发现数量并输出最小审计摘要。

    服务只组合纯评分与风险映射，不保存请求状态、不查询证据库；组织级规则和
    引用验证保留给后续外部依赖接入。
    """

    def assess(self, severity_counts: dict[str, int]) -> dict[str, object]:
        """计算 ``severity_counts`` 的分数及对应风险等级。

        返回只含 ``score`` 与 ``severity`` 的字典；未知级别的处理遵循
        :func:`audit_score`。函数无副作用，复杂度为 O(n)，不验证证据存在性。
        """
        score = audit_score(severity_counts)
        return {"score": score, "severity": classify_risk(score)}

    def execution_audit(self) -> ExecutionAuditService:
        """返回无状态节点审计器，供执行服务在不共享运行状态下按需调用。"""
        return ExecutionAuditService()

    # TODO: 接入证据存储和策略引擎后，验证引用存在性与组织级规则。
