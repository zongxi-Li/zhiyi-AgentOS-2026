"""记忆部件对外暴露的读写合同。

模型只规定记录、检索与策略的资料形状；向量化、持久化和召回排序不在本模块实现。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryType(str, Enum):
    """跨部件一致的记忆分类。"""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    WORKING = "working"
    EVIDENCE = "evidence"


class MemoryRecord(BaseModel):
    """单条可持久化记忆；importance 使用闭区间 [0, 1]。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    memory_id: StrictStr = Field(alias="memoryId", min_length=1, description="记忆记录唯一标识。")
    memory_type: MemoryType = Field(alias="memoryType", description="记录所属的稳定记忆类别。")
    content: dict[str, Any] = Field(description="不绑定具体存储实现的 JSON 内容。")
    scope: StrictStr = Field(default="global", min_length=1, description="记录的可见范围。")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="召回优先级，范围为 0 到 1。")
    tags: list[StrictStr] = Field(default_factory=list, description="帮助检索的稳定标签。")
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt", description="记录创建的 UTC 时间。")
    expires_at: datetime | None = Field(default=None, alias="expiresAt", description="可选的失效 UTC 时间。")


class MemoryQuery(BaseModel):
    """向记忆部件提交的只读查询条件。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    query: StrictStr = Field(min_length=1, description="待匹配的自然语言或结构化查询。")
    memory_types: list[MemoryType] = Field(default_factory=list, alias="memoryTypes", description="限定检索的记忆类别；为空表示全部。")
    scope: StrictStr | None = Field(default=None, description="可选的可见范围限制。")
    tags: list[StrictStr] = Field(default_factory=list, description="需匹配的标签集合。")
    limit: int = Field(default=10, ge=1, le=100, description="最多返回记录数。")


class MemoryPolicy(BaseModel):
    """记忆读写的通用保留与访问策略。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    policy_id: StrictStr = Field(alias="policyId", min_length=1, description="策略唯一标识。")
    allowed_types: list[MemoryType] = Field(alias="allowedTypes", min_length=1, description="该策略允许操作的记忆类别。")
    retention_days: int | None = Field(default=None, alias="retentionDays", ge=1, description="可选的最长保留天数。")
    require_audit: bool = Field(default=False, alias="requireAudit", description="写入是否必须产生审计记录。")


class MemoryWriteBatch(BaseModel):
    """一次原子意图明确的记忆写入批次。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    batch_id: StrictStr = Field(alias="batchId", min_length=1, description="写入批次唯一标识。")
    records: list[MemoryRecord] = Field(min_length=1, description="本批次要写入的记录。")
    policy_id: StrictStr | None = Field(default=None, alias="policyId", description="应用的记忆策略标识。")
    requested_at: datetime = Field(default_factory=_utc_now, alias="requestedAt", description="提交写入的 UTC 时间。")
