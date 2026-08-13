"""AgentOS 的 ACG StateGraph 构建器。

构建器只在编译阶段存在：它接收 Step、控制节点和依赖边，完成后生成不可变的
``ACGExecutionGraph``。运行期不得继续修改拓扑，任何结构变更都必须生成新的 ACG
Blueprint 与新的执行版本，防止检查点恢复到被悄然篡改的图。

第三方来源：LangGraph 1.2.10，commit d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086；
来源模块 ``libs/langgraph/langgraph/graph/state.py``。改写说明与完整 MIT 许可证见
``docs/THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from .graph import ACGConditionalRoute, ACGExecutionGraph, ACGNodeSpec


class ACGStateGraph:
    """一次性可变构建器；编译后产出不可变的 AgentOS 执行图。"""

    def __init__(self) -> None:
        self._specs: dict[str, ACGNodeSpec] = {}
        self._edges: list[tuple[str, str]] = []
        self._compiled = False

    def add_step(
        self,
        node_id: str,
        *,
        communication_mode: str = "STRICT_CONTRACT",
        review_required: bool = False,
    ) -> "ACGStateGraph":
        """登记一个可由 AgentOS 节点执行链调用的 Step。"""
        self._assert_mutable()
        if node_id in self._specs:
            raise ValueError(f"duplicate graph node: {node_id}")
        self._specs[node_id] = ACGNodeSpec(
            node_id=node_id,
            communication_mode=communication_mode,  # type: ignore[arg-type]
            review_required=review_required,
        )
        return self

    def add_control(self, node_id: str, *, condition: ACGConditionalRoute | None = None) -> "ACGStateGraph":
        """登记一个无 Agent 调用的控制节点；可选绑定受限条件路由。"""
        self._assert_mutable()
        if node_id in self._specs:
            raise ValueError(f"duplicate graph node: {node_id}")
        self._specs[node_id] = ACGNodeSpec(node_id=node_id, kind="control", condition=condition)
        return self

    def add_edge(self, source_id: str, target_id: str) -> "ACGStateGraph":
        """登记一条执行依赖边；端点和环在 ``compile`` 时统一校验。"""
        self._assert_mutable()
        self._edges.append((source_id, target_id))
        return self

    def compile(self) -> ACGExecutionGraph:
        """冻结构建器并编译为执行图；之后再次修改会明确报错。"""
        self._assert_mutable()
        self._compiled = True
        return ACGExecutionGraph(nodes=tuple(self._specs), edges=tuple(self._edges), node_specs=dict(self._specs))

    def _assert_mutable(self) -> None:
        """保护编译后拓扑不变，维持 checkpoint 与 Blueprint 的版本一致性。"""
        if self._compiled:
            raise ValueError("StateGraph has already been compiled")


__all__ = ["ACGStateGraph"]
