"""节点执行结果的纯规则审计服务。

该服务只接收输出、Trace 和证据的引用以及已归类的风险数量，返回可重放的策略决定。
它不读取 Agent 输出正文、不调用 Agent，也不会直接修改 WorkflowRun 或执行图状态；
运行器只需消费决定引用及其 outcome 来安排后续治理动作。
"""

from __future__ import annotations

from typing import Any

from components.auditor.algorithms import audit_score
from contracts.governance import AuditRequest, PolicyDecision


class ExecutionAuditService:
    """将节点风险聚合投影为 allow、review 或 deny 的稳定策略决定。"""

    def assess_node(
        self,
        *,
        request: AuditRequest,
        severity_counts: dict[str, int],
        memory_access: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """对一个引用化节点结果执行风险门控。

        critical 表示结果不可进入后续执行，直接拒绝；high 表示需要人工判断而暂停；
        其余已知或未知等级在首期规则中允许通过。评分仅用于可解释性和后续策略演进，
        不会包含审计目标正文或 ContextPack 内容。
        """
        score = audit_score(severity_counts)
        memory_violation = self._memory_access_violation(memory_access)
        policy_refs = ["execution-risk.v1"]
        metadata: dict[str, Any] = {"auditScore": score}
        if memory_access is not None:
            policy_refs.append("memory-access.v1")
            metadata["memoryAccessCompliant"] = memory_violation is None
        if memory_violation is not None:
            outcome = "deny"
            metadata["memoryAccessViolation"] = memory_violation
        elif max(0, severity_counts.get("critical", 0)) > 0:
            outcome = "deny"
        elif max(0, severity_counts.get("high", 0)) > 0:
            outcome = "review"
        else:
            outcome = "allow"
        return PolicyDecision(
            decisionId=f"decision:{request.request_id}",
            subjectRef=request.subject_ref,
            outcome=outcome,
            policyRefs=policy_refs,
            rationale=f"audit score={score}",
            metadata=metadata,
        )

    @staticmethod
    def _memory_access_violation(memory_access: dict[str, Any] | None) -> str | None:
        """校验步骤策略统计的基本不变量，不读取也不记录任何记忆正文。"""
        if memory_access is None:
            return None
        read = memory_access.get("read")
        write = memory_access.get("write")
        read_count = memory_access.get("readCount")
        written = memory_access.get("written")
        tokens_used = memory_access.get("tokensUsed")
        limit = memory_access.get("limit")
        token_budget = memory_access.get("tokenBudget")
        if not all(isinstance(item, bool) for item in (read, write, written)):
            return "memory access flags must be booleans"
        if not isinstance(read_count, int) or isinstance(read_count, bool) or read_count < 0:
            return "memory read count must be a non-negative integer"
        if not isinstance(tokens_used, int) or isinstance(tokens_used, bool) or tokens_used < 0:
            return "memory tokens used must be a non-negative integer"
        if limit is None:
            limit = 10
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            return "memory limit must be an integer between 1 and 100"
        if token_budget is not None and (
            not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 0
        ):
            return "memory token budget must be a non-negative integer or null"
        if not read and read_count:
            return "read disabled but records were injected"
        if not read and tokens_used:
            return "read disabled but memory tokens were used"
        if not write and written:
            return "write disabled but memory was persisted"
        if read_count > limit:
            return "memory read count exceeds declared limit"
        if token_budget is not None and tokens_used > token_budget:
            return "memory tokens used exceeds declared budget"
        return None


__all__ = ["ExecutionAuditService"]
