"""执行请求与执行结果的部件边界合同。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .workflow import GraphNodeRef, GraphRef


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionPackageRef(BaseModel):
    """可被执行器取得的执行包引用，而非具体包内容。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    package_id: StrictStr = Field(alias="packageId", min_length=1, description="执行包的稳定标识。")
    graph: GraphRef = Field(description="执行包对应的工作流图版本。")
    entry_node: GraphNodeRef | None = Field(default=None, alias="entryNode", description="可选的图入口节点。")
    checksum: StrictStr = Field(min_length=1, description="执行包内容的稳定校验和。")
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt", description="执行包创建的 UTC 时间。")


class ExecutionOutcomeRef(BaseModel):
    """一次执行的结果摘要引用，输出本体可由存储部件持有。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    execution_id: StrictStr = Field(alias="executionId", min_length=1, description="一次执行尝试的唯一标识。")
    package_id: StrictStr = Field(alias="packageId", min_length=1, description="产生结果的执行包标识。")
    status: Literal["succeeded", "failed", "cancelled", "pending"] = Field(description="执行的标准终态或待执行状态。")
    output_ref: StrictStr | None = Field(default=None, alias="outputRef", description="输出数据在外部存储中的引用。")
    error_code: StrictStr | None = Field(default=None, alias="errorCode", description="失败时机器可读的错误代码。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="与执行器实现无关的结果元数据。")
    completed_at: datetime | None = Field(default=None, alias="completedAt", description="执行结束的 UTC 时间。")
