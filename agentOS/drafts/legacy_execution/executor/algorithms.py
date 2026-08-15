"""执行器的纯算法出口与可审计摘要工具。"""

import json
from time import perf_counter
from typing import Any

from .graph import RuntimeGraph, RuntimeNode, ready_set


def select_maximum_batch(graph: RuntimeGraph, ready: list[RuntimeNode], max_parallelism: int) -> list[RuntimeNode]:
    """按优先级和 node id 在独立资源键上贪心选择最大确定性批次。"""
    del graph
    selected: list[RuntimeNode] = []
    occupied: set[str] = set()
    for node in sorted(ready, key=lambda item: (-int(item.spec.get("priority", 0)), item.node_id)):
        resource = str((node.current_binding or {}).get("resourceId") or (node.current_binding or {}).get("assignedAgentId") or node.node_id)
        if len(selected) >= max(1, max_parallelism) or resource in occupied:
            continue
        selected.append(node); occupied.add(resource)
    return selected


def summarize(data: Any, *, max_chars: int = 280) -> str:
    """为审计事件生成稳定、有界的输入输出摘要。"""
    try: text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError): text = str(data)
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[:max_chars] + f"…(+{len(text) - max_chars} chars)"


class StepExecutionTimer:
    """记录单个执行步骤自创建起的单调耗时。

    不接受外部输入，``elapsed_ms`` 返回整数毫秒；只读取 ``perf_counter``，
    不修改执行图或共享状态，因此可在同一线程内安全用于审计计时。
    """
    def __init__(self) -> None: self._started = perf_counter()
    def elapsed_ms(self) -> int:
        """返回从构造到当前时刻的非负整数毫秒，不重置起始时间。"""
        return int((perf_counter() - self._started) * 1000)

# 条件分支的完整模型和求值器定义紧随本模块末尾：规划器只声明，执行器才决策。
"""Safe, deterministic condition models and evaluation for runtime IF controls."""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator



class ConditionOperator(str, Enum):
    """受限条件求值支持的比较算子枚举，不允许表达式或代码执行。"""
    EQUALS = "EQUALS"
    IN = "IN"
    EXISTS = "EXISTS"
    BOOLEAN = "BOOLEAN"


class ConditionSpec(BaseModel):
    """描述一次受限 JSON 指针取值与分支边映射。

    输入限定为来源节点、RFC-6901 风格路径、算子和已声明边；模型会拒绝非法
    路径与值类型。该对象是不可执行的数据合同，求值不会调用动态代码或改变图状态。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    source_node_id: str = Field(alias="sourceNodeId", min_length=1)
    json_pointer: str = Field(alias="jsonPointer")
    operator: ConditionOperator
    cases: dict[str, str]
    default_edge_id: str | None = Field(default=None, alias="defaultEdgeId")
    value_type: str = Field(default="string", alias="valueType")

    @field_validator("json_pointer")
    @classmethod
    def _valid_pointer(cls, value: str) -> str:
        if value and not value.startswith("/"):
            raise ValueError("jsonPointer must be empty or begin with '/'")
        return value

    @field_validator("value_type")
    @classmethod
    def _valid_value_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"string", "number", "boolean", "array", "object", "any"}:
            raise ValueError("unsupported condition valueType")
        return normalized


class ConditionalEvaluationResult(BaseModel):
    """保存条件求值的可审计结果。

    记录输入版本、稳定哈希、选择与终止的边以及汇合节点，供图服务一次性应用；
    本模型本身不修改运行图，并由 Pydantic 在构造时校验字段边界。
    """
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    control_node_id: str = Field(alias="controlNodeId")
    source_node_id: str = Field(alias="sourceNodeId")
    source_output_version: int = Field(alias="sourceOutputVersion", ge=0)
    input_hash: str = Field(alias="inputHash")
    resolved_value: Any = Field(alias="resolvedValue")
    selected_case_key: str = Field(alias="selectedCaseKey")
    selected_edge_ids: list[str] = Field(alias="selectedEdgeIds")
    terminated_edge_ids: list[str] = Field(alias="terminatedEdgeIds")
    join_node_id: str = Field(alias="joinNodeId")


class BranchDecision(BaseModel):
    """冻结一次条件分支决策及其图版本依据。

    输出包含被选边、被跳过节点和来源事件，供重放与幂等比对；模型冻结，避免
    决策生成后被调用方原地改写。
    """
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    decision_id: str = Field(alias="decisionId")
    control_node_id: str = Field(alias="controlNodeId")
    source_node_id: str = Field(alias="sourceNodeId")
    source_output_version: int = Field(alias="sourceOutputVersion", ge=0)
    input_hash: str = Field(alias="inputHash")
    selected_case_key: str = Field(alias="selectedCaseKey")
    selected_edge_ids: list[str] = Field(alias="selectedEdgeIds")
    terminated_edge_ids: list[str] = Field(alias="terminatedEdgeIds")
    skipped_node_ids: list[str] = Field(alias="skippedNodeIds")
    join_node_id: str = Field(alias="joinNodeId")
    source_event_id: str = Field(alias="sourceEventId")
    source_patch_id: str = Field(alias="sourcePatchId")
    decided_at_graph_version: int = Field(alias="decidedAtGraphVersion", ge=1)
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="decidedAt"
    )


def condition_input_hash(
    *, source_node_id: str, output_version: int, json_pointer: str, resolved_value: Any
) -> str:
    """为条件输入生成稳定 SHA-256 哈希。

    输入为来源节点、输出版本、JSON 指针和解析值，输出为十六进制摘要；采用稳定
    JSON 序列化，时间复杂度为输入序列化长度 O(n)，不读取或修改共享状态。
    """
    payload = [source_node_id, output_version, json_pointer, resolved_value]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ConditionEvaluationError(ValueError):
    """表示条件定义、类型或分支边不合法的带错误码异常。"""

    def __init__(self, code: str, message: str):
        """以机器可读 ``code`` 和面向调用方的 ``message`` 初始化异常。"""
        super().__init__(message)
        self.code = code


class ConditionEvaluator:
    """执行纯 RFC-6901 风格查找及有限分支选择。

    ``evaluate`` 只读取来源输出和图定义，返回可审计结果而不激活任何边；非法
    指针、类型或未声明边会抛出 ``ConditionEvaluationError``。
    """

    _MISSING = object()

    def evaluate(
        self,
        condition_spec: ConditionSpec,
        source_output: dict[str, Any],
        graph,
        *,
        control_node_id: str,
        join_node_id: str,
        branch_edge_ids: list[str],
    ) -> ConditionalEvaluationResult:
        """按条件规格解析输出并选择一条已声明分支边。

        输入为规格、来源输出、图和控制节点上下文，输出为不可变式结果投影；
        复杂度为 JSON 路径深度加分支边数 O(p+b)，不修改 ``graph``，错误边界
        通过 ``ConditionEvaluationError`` 明确给出。
        """
        source = graph.get_node(condition_spec.source_node_id)
        value = self._resolve_pointer(source_output, condition_spec.json_pointer)
        exists = value is not self._MISSING
        self._validate_type(condition_spec, value, exists)
        case_key = self._select_case(condition_spec, value, exists)
        edge_id = condition_spec.cases.get(case_key)
        if edge_id is None:
            edge_id = condition_spec.default_edge_id
            case_key = "__default__"
        if edge_id is None:
            raise ConditionEvaluationError(
                "CONDITION_NO_MATCH", "condition did not match and has no defaultEdgeId"
            )
        if edge_id not in branch_edge_ids:
            raise ConditionEvaluationError(
                "CONDITION_EDGE_NOT_DECLARED", f"selected edge is not declared: {edge_id}"
            )
        resolved = None if value is self._MISSING else value
        input_hash = condition_input_hash(
            source_node_id=source.node_id,
            output_version=source.output_version,
            json_pointer=condition_spec.json_pointer,
            resolved_value=resolved,
        )
        return ConditionalEvaluationResult(
            controlNodeId=control_node_id,
            sourceNodeId=source.node_id,
            sourceOutputVersion=source.output_version,
            inputHash=input_hash,
            resolvedValue=resolved,
            selectedCaseKey=case_key,
            selectedEdgeIds=[edge_id],
            terminatedEdgeIds=[item for item in branch_edge_ids if item != edge_id],
            joinNodeId=join_node_id,
        )

    @classmethod
    def _resolve_pointer(cls, document: Any, pointer: str) -> Any:
        if pointer == "":
            return document
        current = document
        for raw in pointer.split("/")[1:]:
            token = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                return cls._MISSING
        return current

    @staticmethod
    def _case_key(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        return str(value)

    def _select_case(self, spec: ConditionSpec, value: Any, exists: bool) -> str:
        if spec.operator == ConditionOperator.EXISTS:
            return "true" if exists else "false"
        if not exists:
            return "__missing__"
        if spec.operator == ConditionOperator.BOOLEAN:
            if not isinstance(value, bool):
                raise ConditionEvaluationError("CONDITION_TYPE_MISMATCH", "BOOLEAN requires bool")
            return "true" if value else "false"
        if spec.operator == ConditionOperator.IN:
            if not isinstance(value, list):
                raise ConditionEvaluationError("CONDITION_TYPE_MISMATCH", "IN requires array")
            keys = {self._case_key(item) for item in value}
            return next((key for key in spec.cases if key in keys), "__no_match__")
        return self._case_key(value)

    @staticmethod
    def _validate_type(spec: ConditionSpec, value: Any, exists: bool) -> None:
        if not exists or spec.operator == ConditionOperator.EXISTS or spec.value_type == "any":
            return
        matches = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }[spec.value_type]
        if not matches:
            raise ConditionEvaluationError(
                "CONDITION_TYPE_MISMATCH", f"expected {spec.value_type}"
            )


def conditional_branch_exclusive_nodes(graph, control_node) -> dict[str, set[str]]:
    """计算每条条件分支在显式汇合点之前独占的节点集合。

    输入图与控制节点只被读取，返回按分支边标识组织的节点集合；深度优先遍历
    检测未汇合、非法边和分支共享节点并抛出 ``ConditionEvaluationError``。
    时间复杂度为 O(V+E)。
    """

    edges = {edge.edge_id: edge for edge in graph.edges}
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if getattr(edge.edge_type, "value", edge.edge_type) == "dependency":
            adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    join_id = control_node.join_node_id
    if not join_id:
        raise ConditionEvaluationError("CONDITIONAL_JOIN_MISSING", control_node.node_id)

    results: dict[str, set[str]] = {}
    for edge_id in control_node.branch_edge_ids:
        edge = edges.get(edge_id)
        if (
            edge is None
            or edge.source_id != control_node.node_id
            or edge.edge_type not in {EdgeType.DEPENDENCY, EdgeType.CONTROL_FLOW}
        ):
            raise ConditionEvaluationError("CONDITIONAL_BRANCH_EDGE_INVALID", edge_id)
        visited: set[str] = set()
        visiting: set[str] = set()

        def walk(node_id: str) -> bool:
            if node_id == join_id:
                return True
            if node_id in visiting:
                return False
            if node_id in visited:
                return True
            visiting.add(node_id)
            targets = adjacency.get(node_id, [])
            reaches = bool(targets) and all(walk(target) for target in targets)
            visiting.remove(node_id)
            if reaches:
                visited.add(node_id)
            return reaches

        if not walk(edge.target_id):
            raise ConditionEvaluationError(
                "CONDITIONAL_BRANCH_DOES_NOT_JOIN", f"branch {edge_id} does not converge"
            )
        results[edge_id] = visited

    edge_ids = list(results)
    for index, edge_id in enumerate(edge_ids):
        for other_id in edge_ids[index + 1 :]:
            shared = results[edge_id] & results[other_id]
            if shared:
                raise ConditionEvaluationError(
                    "CONDITIONAL_BRANCH_SHARED_NODE",
                    f"branches share nodes before join: {sorted(shared)}",
                )
    return results


__all__ = [
    "BranchDecision",
    "ConditionEvaluationError",
    "ConditionEvaluator",
    "ConditionOperator",
    "ConditionSpec",
    "ConditionalEvaluationResult",
    "condition_input_hash",
    "conditional_branch_exclusive_nodes",
]
