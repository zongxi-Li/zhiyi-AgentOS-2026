"""将 ACG Blueprint 编译为 AgentOS 融合执行图。

编译器是规划层到执行层的唯一入口：Step 转为可调度节点，DEPENDENCY 转为执行边，
IF 控制节点转为受限条件路由，``reviewRequired`` 转为中断点。LangGraph 对象不会
暴露到 contracts；输入与输出始终是 AgentOS 自己的 Blueprint/执行图。

首期允许 ``STRICT_CONTRACT`` 和 ``EVENT``。``BLACKBOARD``、``DEBATE`` 一旦出现
立即拒绝，绝不降级成其它通信模式，以避免绕过治理语义。

第三方来源：LangGraph 1.2.10，commit d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086；
来源模块 ``libs/langgraph/langgraph/graph/state.py``。改写说明与完整 MIT 许可证见
``docs/THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from components.executor.graph import ACGConditionalRoute, ACGExecutionGraph, ACGNodeSpec
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from support.acg.models import ACGBlueprint, ControlNode, ControlType, EdgeType


class UnsupportedCommunicationModeError(ValueError):
    """蓝图声明了当前版本无法安全执行的通信模式。"""


class ACGGraphCompiler:
    """编译 Step、依赖、控制节点、审核点和受治理的通信模式。"""

    supported_communication_modes = {"STRICT_CONTRACT", "EVENT"}

    def compile(self, blueprint: ACGBlueprint, *, run_id: str | None = None) -> ACGExecutionGraph:
        """将一个已规划 Blueprint 转换为运行期的不可变执行图。"""
        node_specs: dict[str, ACGNodeSpec] = {}
        for step in blueprint.step_nodes():
            mode = str(step.metadata.get("communicationMode", "STRICT_CONTRACT")).upper()
            if mode not in self.supported_communication_modes:
                raise UnsupportedCommunicationModeError(
                    f"communication mode {mode} is not available in the first LangGraph migration release"
                )
            # EVENT 是纯通知关系，只能通过引用说明事件来源；若仍声明 from 字段，
            # 下游将有机会把它当作数据管道读取上游正文，必须在编译期拒绝。
            if mode == "EVENT" and isinstance(step.input_spec.get("from"), dict):
                raise ValueError(
                    f"EVENT step {step.node_id} cannot declare inputSpec.from fields"
                )
            node_specs[step.node_id] = ACGNodeSpec(
                node_id=step.node_id,
                communication_mode=mode,  # type: ignore[arg-type]
                review_required=step.review_required,
            )
        for control in (node for node in blueprint.nodes if isinstance(node, ControlNode)):
            condition = self._compile_condition(blueprint, control)
            node_specs[control.node_id] = ACGNodeSpec(
                node_id=control.node_id,
                kind="control",
                condition=condition,
            )
        executable_ids = set(node_specs)
        edges = tuple(
            (edge.source_id, edge.target_id)
            for edge in blueprint.edges
            if edge.edge_type == EdgeType.DEPENDENCY
            and edge.source_id in executable_ids
            and edge.target_id in executable_ids
        )
        return ACGExecutionGraph(
            nodes=tuple(node.node_id for node in blueprint.nodes if node.node_id in executable_ids),
            edges=edges,
            node_specs=node_specs,
            communication_manifest=self._compile_manifest(
                blueprint=blueprint,
                edges=edges,
                run_id=run_id,
            ),
        )

    @staticmethod
    def _compile_manifest(
        *,
        blueprint: ACGBlueprint,
        edges: tuple[tuple[str, str], ...],
        run_id: str | None,
    ) -> CommunicationManifest | None:
        """把 Step 依赖映射为内部通信许可，缺少运行标识时不创建运行期 Manifest。"""
        if not run_id:
            return None
        steps = {step.node_id: step for step in blueprint.step_nodes()}
        metadata = blueprint.metadata if isinstance(blueprint.metadata, dict) else {}
        raw_run_budget = metadata.get("communicationBudget")
        if isinstance(raw_run_budget, bool):
            raise ValueError("communication budget must be a non-negative integer")
        try:
            run_budget = int(raw_run_budget) if raw_run_budget is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError("communication budget must be a non-negative integer") from exc
        if run_budget is not None and run_budget < 0:
            raise ValueError("communication budget must be a non-negative integer")
        rules: list[CommunicationRule] = []
        step_budgets: dict[str, int] = {}
        channel_budgets: dict[str, int] = {}
        communication_channels: dict[tuple[str, str], list[str] | None] = {
            (source_id, target_id): None for source_id, target_id in edges
        }
        for edge in blueprint.edges_of_type(EdgeType.COMMUNICATION):
            communication_channels[(edge.source_id, edge.target_id)] = list(edge.data_fields)

        for (source_id, target_id), edge_fields in communication_channels.items():
            source = steps.get(source_id)
            target = steps.get(target_id)
            if source is None or target is None:
                continue
            from_map = target.input_spec.get("from") if isinstance(target.input_spec, dict) else None
            declared_fields = (
                edge_fields
                if edge_fields
                else (from_map.get(source_id, []) if isinstance(from_map, dict) else [])
            )
            if not isinstance(declared_fields, list):
                raise ValueError(f"communication fields for {source_id}->{target_id} must be a list")
            # 无精确 slot 声明时，以生产步骤的公开输出合同字段作为读取上界；这不是
            # 必填输入契约，Agent 仍可在运行时只请求其中需要的部分。
            if not declared_fields:
                properties = source.output_spec.get("properties", {}) if isinstance(source.output_spec, dict) else {}
                declared_fields = list(properties) if isinstance(properties, dict) else []
            metadata = target.metadata if isinstance(target.metadata, dict) else {}
            max_tokens = int(metadata.get("communicationBudget", 4096))
            if max_tokens < 0:
                raise ValueError(f"communication budget for {target_id} must not be negative")
            channel = f"{source_id}:{target_id}"
            rules.append(
                CommunicationRule(
                    producer_step_id=source_id,
                    consumer_step_id=target_id,
                    allowed_fields=tuple(str(field) for field in declared_fields),
                    channel=channel,
                    max_tokens=max_tokens,
                )
            )
            step_budgets[target_id] = max_tokens
            channel_budgets[channel] = max_tokens
        return CommunicationManifest(
            run_id=run_id,
            rules=tuple(rules),
            run_budget=run_budget,
            step_budgets=step_budgets,
            channel_budgets=channel_budgets,
        )

    @staticmethod
    def _compile_condition(blueprint: ACGBlueprint, control: ControlNode) -> ACGConditionalRoute | None:
        """把 IF 的 case→edge 映射转换为 case→目标节点的受限路由。"""
        if control.control_type != ControlType.IF:
            return None
        spec = control.condition_spec
        if spec is None:
            raise ValueError(f"IF control {control.node_id} has no conditionSpec")
        edge_by_id = {edge.edge_id: edge for edge in blueprint.edges}
        try:
            targets = {case: edge_by_id[edge_id].target_id for case, edge_id in spec.cases.items()}
            default = edge_by_id[spec.default_edge_id].target_id if spec.default_edge_id else None
        except KeyError as exc:
            raise ValueError(f"IF control {control.node_id} references an unknown branch edge") from exc
        return ACGConditionalRoute(
            source_step_id=spec.source_node_id,
            json_pointer=spec.json_pointer,
            operator=spec.operator.value,
            targets_by_case=targets,
            default_target=default,
        )


__all__ = ["ACGGraphCompiler", "UnsupportedCommunicationModeError"]
