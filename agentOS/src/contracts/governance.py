"""治理部件需要的审计请求、发现与策略决定合同。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditRequest(BaseModel):
    """请求治理部件检查某个目标的输入。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    request_id: StrictStr = Field(alias="requestId", min_length=1, description="审计请求唯一标识。")
    subject_ref: StrictStr = Field(alias="subjectRef", min_length=1, description="被审计对象的稳定引用。")
    audit_type: StrictStr = Field(alias="auditType", min_length=1, description="审计的类别或规则集名称。")
    evidence_refs: list[StrictStr] = Field(default_factory=list, alias="evidenceRefs", description="可供审计读取的证据引用。")
    requested_at: datetime = Field(default_factory=_utc_now, alias="requestedAt", description="请求发起的 UTC 时间。")


class AuditFinding(BaseModel):
    """一条可被记录和处理的审计发现。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    finding_id: StrictStr = Field(alias="findingId", min_length=1, description="审计发现唯一标识。")
    request_id: StrictStr = Field(alias="requestId", min_length=1, description="来源审计请求标识。")
    severity: Literal["info", "low", "medium", "high", "critical"] = Field(description="标准化风险等级。")
    code: StrictStr = Field(min_length=1, description="机器可读的发现代码。")
    message: StrictStr = Field(min_length=1, description="面向操作者的发现说明。")
    evidence_refs: list[StrictStr] = Field(default_factory=list, alias="evidenceRefs", description="支撑此发现的证据引用。")


class PolicyDecision(BaseModel):
    """策略评估的允许、拒绝或需要人工复核结果。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    decision_id: StrictStr = Field(alias="decisionId", min_length=1, description="策略决定唯一标识。")
    subject_ref: StrictStr = Field(alias="subjectRef", min_length=1, description="决策作用对象的稳定引用。")
    outcome: Literal["allow", "deny", "review"] = Field(description="策略评估结果。")
    policy_refs: list[StrictStr] = Field(default_factory=list, alias="policyRefs", description="参与决定的策略标识。")
    rationale: StrictStr = Field(min_length=1, description="决定理由。")
    decided_at: datetime = Field(default_factory=_utc_now, alias="decidedAt", description="决定产生的 UTC 时间。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="可扩展的治理元数据。")
