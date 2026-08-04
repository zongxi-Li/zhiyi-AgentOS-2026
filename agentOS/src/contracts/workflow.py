"""工作流图的跨部件引用合同。

合同刻意只传递图的引用与边界信息，图构建、拓扑校验等业务逻辑仍属于规划部件。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class GraphRef(BaseModel):
    """一个可版本化工作流图的轻量引用。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    graph_id: StrictStr = Field(alias="graphId", min_length=1, description="工作流图的稳定标识。")
    version: StrictStr = Field(min_length=1, description="图定义或快照的版本号。")
    checksum: StrictStr | None = Field(default=None, min_length=1, description="图内容的稳定校验和。")


class GraphNodeRef(BaseModel):
    """图中节点的引用，不携带执行器或规划器实现。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    graph: GraphRef = Field(description="所属工作流图引用。")
    node_id: StrictStr = Field(alias="nodeId", min_length=1, description="节点在图内的唯一标识。")
    node_type: StrictStr = Field(alias="nodeType", min_length=1, description="节点种类，例如 step、gateway。")
    label: StrictStr | None = Field(default=None, description="供展示与审计使用的可读标签。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="节点的可扩展元数据。")


class GraphEdgeRef(BaseModel):
    """两个图节点之间的有向连接引用。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    graph: GraphRef = Field(description="所属工作流图引用。")
    edge_id: StrictStr = Field(alias="edgeId", min_length=1, description="边在图内的唯一标识。")
    source_node_id: StrictStr = Field(alias="sourceNodeId", min_length=1, description="有向边的起始节点标识。")
    target_node_id: StrictStr = Field(alias="targetNodeId", min_length=1, description="有向边的目标节点标识。")
    relation: Literal["sequence", "condition", "data", "control"] = Field(
        default="sequence", description="边的稳定关系类型。"
    )
