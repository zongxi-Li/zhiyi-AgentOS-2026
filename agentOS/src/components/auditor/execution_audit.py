"""节点执行结果的纯规则审计服务。

该服务只接收输出、Trace 和证据的引用以及已归类的风险数量，返回可重放的策略决定。
它不读取 Agent 输出正文、不调用 Agent，也不会直接修改 WorkflowRun 或执行图状态；
运行器只需消费决定引用及其 outcome 来安排后续治理动作。
"""

from __future__ import annotations

from components.auditor.algorithms import audit_score
from contracts.governance import AuditRequest, PolicyDecision


class ExecutionAuditService:
    """将节点风险聚合投影为 allow、review 或 deny 的稳定策略决定。"""

    def assess_node(
        self,
        *,
        request: AuditRequest,
        severity_counts: dict[str, int],
    ) -> PolicyDecision:
        """对一个引用化节点结果执行风险门控。

        critical 表示结果不可进入后续执行，直接拒绝；high 表示需要人工判断而暂停；
        其余已知或未知等级在首期规则中允许通过。评分仅用于可解释性和后续策略演进，
        不会包含审计目标正文或 ContextPack 内容。
        """
        score = audit_score(severity_counts)
        if max(0, severity_counts.get("critical", 0)) > 0:
            outcome = "deny"
        elif max(0, severity_counts.get("high", 0)) > 0:
            outcome = "review"
        else:
            outcome = "allow"
        return PolicyDecision(
            decisionId=f"decision:{request.request_id}",
            subjectRef=request.subject_ref,
            outcome=outcome,
            policyRefs=["execution-risk.v1"],
            rationale=f"audit score={score}",
            metadata={"auditScore": score},
        )


__all__ = ["ExecutionAuditService"]
