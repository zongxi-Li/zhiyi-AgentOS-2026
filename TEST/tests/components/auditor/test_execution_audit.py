"""节点执行审计决定的确定性规则测试。"""

from __future__ import annotations

from components.auditor.execution_audit import ExecutionAuditService
from contracts.governance import AuditRequest


def _request() -> AuditRequest:
    """构造只携带引用而不带输出正文的审计请求。"""
    return AuditRequest(
        requestId="audit-1",
        subjectRef="output:run-1:legal:1",
        auditType="node_output",
        evidenceRefs=["trace:legal"],
    )


def test_high_risk_node_output_returns_review_decision() -> None:
    """高或严重发现必须暂停交由审核，不能被风险评分静默允许。"""
    decision = ExecutionAuditService().assess_node(
        request=_request(),
        severity_counts={"high": 1},
    )

    assert decision.outcome == "review"
    assert decision.subject_ref == "output:run-1:legal:1"
    assert decision.policy_refs == ["execution-risk.v1"]


def test_execution_audit_denies_critical_findings() -> None:
    """严重发现直接拒绝，避免把不可接受结果放入审核续跑路径。"""
    decision = ExecutionAuditService().assess_node(
        request=_request(),
        severity_counts={"critical": 1},
    )

    assert decision.outcome == "deny"


def test_execution_audit_allows_unknown_severity_without_evidence_leakage() -> None:
    """未知严重度按零权重处理，决定元数据不得复制输出正文。"""
    decision = ExecutionAuditService().assess_node(
        request=_request(),
        severity_counts={"future-level": 3},
    )

    assert decision.outcome == "allow"
    assert decision.metadata == {"auditScore": 0}


def test_execution_audit_denies_inconsistent_memory_access_claim() -> None:
    """声明不读取记忆却上报读取数量时，审计必须阻断节点产物提交。"""
    decision = ExecutionAuditService().assess_node(
        request=_request(),
        severity_counts={},
        memory_access={
            "policyId": "no-read",
            "read": False,
            "readCount": 1,
            "write": False,
            "written": False,
            "tokensUsed": 0,
        },
    )

    assert decision.outcome == "deny"
    assert decision.policy_refs == ["execution-risk.v1", "memory-access.v1"]
    assert decision.metadata == {
        "auditScore": 0,
        "memoryAccessCompliant": False,
        "memoryAccessViolation": "read disabled but records were injected",
    }


def test_execution_audit_denies_memory_access_over_declared_budget() -> None:
    """条数或内容量超过步骤声明上限时，审计必须拒绝而不是信任调用方。"""
    decision = ExecutionAuditService().assess_node(
        request=_request(),
        severity_counts={},
        memory_access={
            "policyId": "bounded",
            "read": True,
            "readCount": 2,
            "write": False,
            "written": False,
            "limit": 1,
            "tokenBudget": 10,
            "tokensUsed": 11,
        },
    )

    assert decision.outcome == "deny"
    assert decision.metadata["memoryAccessViolation"] == "memory read count exceeds declared limit"
