from __future__ import annotations

import pytest

from components.executor.graph import ACGExecutionGraph
from contracts.resource import ExecutionBinding as WknExecutionBinding, ResourceType
from domain.identity_graph import IdentityRelation, IdentityResolver
from domain.repository import IdentityConflictError
from runtime.v2 import (
    PlannerIdentityBridge,
    TaskPlanNode,
    AcgIdentityLifecycleService,
    WknIdentityLifecycleAdapter,
)
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode


@pytest.fixture
def foundation():
    runtime = AcgIdentityLifecycleService(SQLiteV2Repositories(SQLiteV2Storage(":memory:")))
    bridge = WknIdentityLifecycleAdapter(runtime, runtime.repositories)
    try:
        yield runtime, bridge
    finally:
        runtime.close()


def _registered_chain(
    runtime: AcgIdentityLifecycleService,
    bridge: WknIdentityLifecycleAdapter,
):
    task = runtime.create_task(user_id="user-1", goal="审查软件开发合同")
    extract = runtime.create_task_node(
        task_id=task.task_id, title="提取条款", objective="提取付款相关条款"
    )
    risk = runtime.create_task_node(
        task_id=task.task_id,
        parent_node_id=extract.node_id,
        title="分析风险",
        objective="分析付款风险",
    )
    wkn_blueprint = ACGBlueprint(
        graphId="acg_0123456789ab",
        taskId=task.task_id,
        nodes=[
            StepNode(
                nodeId="extract", name="提取条款", agentName="合同智能体",
                capability="contract.extract",
            ),
            StepNode(
                nodeId="risk", name="分析风险", agentName="合同智能体",
                capability="contract.risk",
            ),
        ],
        edges=[ACGEdge(
            edgeId="edge_extract_risk",
            sourceId="extract",
            targetId="risk",
            edgeType=EdgeType.DEPENDENCY,
        )],
    )
    blueprint = bridge.register_blueprint(
        task_id=task.task_id,
        version=1,
        wkn_blueprint=wkn_blueprint,
        task_node_bindings={extract.node_id: "extract", risk.node_id: "risk"},
    )
    return task, extract, risk, blueprint


def _wkn_binding(run_id: str, attempt_id: str, step_id: str) -> WknExecutionBinding:
    return WknExecutionBinding(
        bindingId=f"binding:{run_id}:{step_id}:{attempt_id}",
        runId=run_id,
        stepId=step_id,
        attemptId=attempt_id,
        resourceId="agent-contract-1",
        resourceType=ResourceType.AGENT,
        snapshotVersion=3,
        metadata={"score": 0.95},
    )


def test_planner_bridge_records_only_semantic_task_tree(foundation) -> None:
    runtime, _bridge = foundation
    task = runtime.create_task(user_id="user-1", goal="审查合同")
    nodes = PlannerIdentityBridge(runtime).record_task_tree(task.task_id, [
        TaskPlanNode(key="extract", title="提取条款", objective="识别付款条款"),
        TaskPlanNode(
            key="risk", parentKey="extract", title="分析风险", objective="判断付款风险"
        ),
    ])

    assert nodes[1].parent_node_id == nodes[0].node_id
    assert all(node.node_id.startswith("node_") for node in nodes)


def test_planner_bridge_rejects_nested_execution_identity(foundation) -> None:
    runtime, _bridge = foundation
    task = runtime.create_task(user_id="user-1", goal="审查合同")

    with pytest.raises(IdentityConflictError, match="cannot select execution identities"):
        PlannerIdentityBridge(runtime).record_task_tree(task.task_id, [TaskPlanNode(
            key="risk",
            title="分析风险",
            objective="判断风险",
            metadata={"routing": {"agentId": "legal-agent"}},
        )])


def test_bridge_delegates_compilation_to_wkn_kernel(foundation) -> None:
    runtime, bridge = foundation
    task, extract, _risk, blueprint = _registered_chain(runtime, bridge)
    run = runtime.create_run(task_id=task.task_id, blueprint_id=blueprint.blueprint_id)

    graph = bridge.compile(blueprint.blueprint_id, run_id=run.run_id)

    assert isinstance(graph, ACGExecutionGraph)
    assert graph.nodes == ("extract", "risk")
    assert graph.edges == (("extract", "risk"),)
    assert extract.node_id != "extract"
    assert blueprint.graph_id == "acg_0123456789ab"


def test_wkn_binding_and_lifecycle_resolve_complete_origin(foundation) -> None:
    runtime, bridge = foundation
    task, _extract, risk, blueprint = _registered_chain(runtime, bridge)
    run = runtime.create_run(task_id=task.task_id, blueprint_id=blueprint.blueprint_id)
    attempt = runtime.create_attempt(run_id=run.run_id, node_id=risk.node_id)
    binding = bridge.record_scheduling_binding(
        attempt_id=attempt.attempt_id,
        wkn_binding=_wkn_binding(run.run_id, attempt.attempt_id, "risk"),
        agent_id="agent-contract-1",
        model_id="legal-model-1",
    )
    context = runtime.create_context(run.run_id)
    running = bridge.start_execution(context, input={"clause": "30日内付款"})
    execution = bridge.finish_execution(
        context,
        running.step_execution_id,
        output={"risk": "付款期限风险"},
        evidence_ids=["evidence:contract:42"],
        memory_ids=["memory:run:42"],
    )

    resolver = IdentityResolver(runtime.repositories)
    origin = resolver.resolve_execution_origin(execution.step_execution_id)
    assert origin.user_task.task_id == task.task_id
    assert origin.task_node.node_id == risk.node_id
    assert origin.task_node_binding.acg_node_id == "risk"
    assert origin.execution_binding.binding_id == binding.binding_id
    assert origin.execution_binding.metadata["wknBindingId"].startswith("binding:")
    assert {(link.target_id, link.relation_type) for link in resolver.resolve_provenance(
        execution.step_execution_id
    )} == {
        ("evidence:contract:42", IdentityRelation.PRODUCES),
        ("memory:run:42", IdentityRelation.WRITES),
    }


def test_bridge_rejects_wkn_binding_from_another_attempt(foundation) -> None:
    runtime, bridge = foundation
    task, extract, _risk, blueprint = _registered_chain(runtime, bridge)
    run = runtime.create_run(task_id=task.task_id, blueprint_id=blueprint.blueprint_id)
    attempt = runtime.create_attempt(run_id=run.run_id, node_id=extract.node_id)

    with pytest.raises(IdentityConflictError, match="does not match Attempt"):
        bridge.record_scheduling_binding(
            attempt_id=attempt.attempt_id,
            wkn_binding=_wkn_binding(run.run_id, "attempt_000000000000", "extract"),
            agent_id="agent-contract-1",
            model_id="legal-model-1",
        )


def test_bridge_rejects_compiling_blueprint_for_another_run(foundation) -> None:
    runtime, bridge = foundation
    task, _extract, _risk, blueprint_v1 = _registered_chain(runtime, bridge)
    extra = runtime.create_task_node(
        task_id=task.task_id, title="输出报告", objective="输出审查报告"
    )
    blueprint_v2 = bridge.register_blueprint(
        task_id=task.task_id,
        version=2,
        wkn_blueprint=ACGBlueprint(
            graphId="acg_222222222222",
            taskId=task.task_id,
            nodes=[StepNode(nodeId="report", name="输出报告", agentName="合同智能体")],
        ),
        task_node_bindings={extra.node_id: "report"},
    )
    run = runtime.create_run(task_id=task.task_id, blueprint_id=blueprint_v1.blueprint_id)

    with pytest.raises(IdentityConflictError, match="do not belong to the Run"):
        bridge.compile(blueprint_v2.blueprint_id, run_id=run.run_id)


def test_bridge_rejects_task_node_substitution_for_wkn_node(foundation) -> None:
    runtime, bridge = foundation
    task = runtime.create_task(user_id="user-1", goal="目标")
    node = runtime.create_task_node(task_id=task.task_id, title="节点", objective="执行")
    wkn_blueprint = ACGBlueprint(
        graphId="acg_abcdefabcdef",
        taskId=task.task_id,
        nodes=[StepNode(nodeId=node.node_id, name="错误复用", agentName="合同智能体")],
    )

    with pytest.raises(IdentityConflictError, match="remain distinct"):
        bridge.register_blueprint(
            task_id=task.task_id,
            version=1,
            wkn_blueprint=wkn_blueprint,
            task_node_bindings={node.node_id: node.node_id},
        )


def test_complete_identity_graph_survives_sqlite_reopen(tmp_path) -> None:
    db_path = tmp_path / "identity-graph.sqlite3"
    first = AcgIdentityLifecycleService.from_sqlite(db_path)
    first_bridge = WknIdentityLifecycleAdapter(first, first.repositories)
    task, extract, _risk, blueprint = _registered_chain(first, first_bridge)
    run = first.create_run(task_id=task.task_id, blueprint_id=blueprint.blueprint_id)
    attempt = first.create_attempt(run_id=run.run_id, node_id=extract.node_id)
    first_bridge.record_scheduling_binding(
        attempt_id=attempt.attempt_id,
        wkn_binding=_wkn_binding(run.run_id, attempt.attempt_id, "extract"),
        agent_id="agent-contract-1",
        model_id="legal-model-1",
    )
    context = first.create_context(run.run_id)
    running = first_bridge.start_execution(context, input={"contract": "persisted"})
    execution = first_bridge.finish_execution(
        context, running.step_execution_id, output={"ok": True}
    )
    first.close()

    second = AcgIdentityLifecycleService.from_sqlite(db_path)
    try:
        origin = IdentityResolver(second.repositories).resolve_execution_origin(
            execution.step_execution_id
        )
        assert origin.user_task.task_id == task.task_id
        assert origin.task_node.node_id == extract.node_id
        assert origin.execution_binding.resource_id == "agent-contract-1"
    finally:
        second.close()
