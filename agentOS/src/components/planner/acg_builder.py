"""根据目录描述符和已解析绑定构造通用 ACG 图。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from contracts.planning import TaskNodeImplementationBinding, TaskPlan
from support.acg.models import (
    ACGBlueprint,
    ACGEdge,
    AgentNode,
    ControlNode,
    ControlType,
    EdgeType,
    EvidenceNode,
    MemoryNode,
    ParallelSpec,
    ConsensusSpec,
    StepNode,
    validate_blueprint,
    promote_workflow_to_acg,
)
from support.acg.models import CapabilityCatalog
from .cognitive_router import CollaborationNetwork
from support.acg.models import build_default_capability_catalog
from support.acg.models import TaskSemanticProfile

if TYPE_CHECKING:
    from .algorithms import PlanningVariant


@dataclass(frozen=True)
class ACGBuildResult:
    blueprint: ACGBlueprint
    bindings: tuple[TaskNodeImplementationBinding, ...]


class ACGBuilder:
    """依据能力描述符的依赖与合同构造单个可执行 ACG 图。"""

    def __init__(self, capability_catalog: CapabilityCatalog | None = None) -> None:
        self.capability_catalog = capability_catalog or build_default_capability_catalog()

    def build(
        self,
        *,
        task_id: str,
        profile: TaskSemanticProfile,
        network: CollaborationNetwork,
        task_plan: TaskPlan,
        variant: "PlanningVariant | None" = None,
    ) -> ACGBlueprint:
        """从语义画像和已解析绑定构造并校验可执行 ACG。

        输入网络必须已覆盖所需能力；返回的图按能力依赖建立数据与控制边。该方法只创建
        内存蓝图，不注册、不持久化也不调度；目录无效或绑定为空时抛出 ``ValueError``。
        """
        self.capability_catalog.validate()
        if not network.bindings:
            raise ValueError("ACG planning produced no capability bindings")
        if task_plan.task_id != task_id:
            raise ValueError("TaskPlan taskId does not match ACG build task")
        plan_key_by_capability = {
            str(node.capability_requirements[0]): node.key
            for node in task_plan.nodes
            if node.capability_requirements
        }
        selected_capabilities = {binding.capability for binding in network.bindings}
        if set(plan_key_by_capability) != selected_capabilities:
            raise ValueError(
                "TaskPlan capabilities must exactly cover ACG capability bindings"
            )

        blueprint = ACGBlueprint(
            taskId=task_id,
            objective=profile.primary_goal,
            complexityLevel=profile.estimated_complexity,
            metadata={
                "generatedBy": "generic_acg_builder",
                "domainHint": profile.domain_hint,
                "entropyBudget": profile.entropy_budget,
                "estimatedEntropy": network.estimated_entropy,
            },
        )
        if variant is not None:
            blueprint.metadata["planningVariantId"] = variant.variant_id
        selected = [binding.capability for binding in network.bindings]
        selected_set = set(selected)
        descriptors = {
            capability_id: self.capability_catalog.get(capability_id)
            for capability_id in selected
        }
        data_dependencies = {
            capability_id: self._selected_dependencies(
                capability_id,
                selected_set,
                optional_dependencies=(
                    variant.optional_for(capability_id) if variant else None
                ),
            )
            for capability_id in selected
        }
        control_dependencies = {
            capability_id: self._minimal_dependencies(
                data_dependencies[capability_id],
                data_dependencies,
            )
            for capability_id in selected
        }

        steps, step_by_capability = self._build_steps(
            blueprint,
            network,
            descriptors,
            data_dependencies,
            plan_key_by_capability,
        )
        self._wire_execution_graph(
            blueprint,
            selected,
            steps,
            step_by_capability,
            descriptors,
            control_dependencies,
            enable_parallel_controls=(
                variant.enable_parallel_controls if variant else True
            ),
        )
        self._wire_data_contracts(
            blueprint,
            selected,
            step_by_capability,
            descriptors,
            data_dependencies,
        )
        blueprint.touch()
        validate_blueprint(blueprint)
        return blueprint

    def build_template(self, *, workflow, task_plan: TaskPlan) -> ACGBuildResult:
        """Promote an execution template and bind it to declared Planner semantics."""
        blueprint = promote_workflow_to_acg(workflow, task_id=task_plan.task_id)
        return self.finalize(blueprint=blueprint, task_plan=task_plan)

    def finalize(
        self,
        *,
        blueprint: ACGBlueprint,
        task_plan: TaskPlan,
    ) -> ACGBuildResult:
        """Publish the Builder-owned, complete semantic-to-execution mapping."""
        steps = blueprint.step_nodes()
        if len(steps) != len(task_plan.nodes):
            raise ValueError(
                "Blueprint implementation bindings must cover the complete TaskPlan"
            )
        for step, node in zip(steps, task_plan.nodes):
            step.metadata["taskPlanKey"] = node.key
        bindings = tuple(
            TaskNodeImplementationBinding(
                planNodeKey=node.key,
                acgNodeId=step.node_id,
            )
            for step, node in zip(steps, task_plan.nodes)
        )
        if {item.plan_node_key for item in bindings} != {
            node.key for node in task_plan.nodes
        }:
            raise ValueError(
                "Blueprint implementation bindings must cover the complete TaskPlan"
            )
        return ACGBuildResult(blueprint=blueprint, bindings=bindings)

    def _build_steps(
        self,
        blueprint,
        network,
        descriptors,
        data_dependencies,
        plan_key_by_capability,
    ) -> tuple[list[StepNode], dict[str, StepNode]]:
        used_ids: set[str] = set()
        agent_nodes: dict[str, str] = {}
        steps: list[StepNode] = []
        step_by_capability: dict[str, StepNode] = {}

        for binding in network.bindings:
            descriptor = descriptors[binding.capability]
            node_id = self._step_id(binding.agent_name, descriptor.capability_id, used_ids)
            used_ids.add(node_id)
            from_map = {
                self._dependency_node_id(network, dependency): self._output_fields(
                    descriptors[dependency].output_contract
                )
                for dependency in data_dependencies[descriptor.capability_id]
            }
            input_spec = dict(descriptor.input_contract)
            if from_map:
                input_spec = {"from": from_map, "schema": dict(descriptor.input_contract)}
            step = StepNode(
                nodeId=node_id,
                name=descriptor.display_name,
                goal=descriptor.description or f"Execute {descriptor.display_name}",
                agentName=binding.agent_name,
                capability=descriptor.capability_id,
                inputSpec=input_spec,
                outputSpec=dict(descriptor.output_contract),
                reviewRequired=descriptor.requires_review,
                metadata={
                    "capabilityId": descriptor.capability_id,
                    "planningStage": descriptor.planning_stage,
                    "role": descriptor.planning_stage,
                    "dependsOn": list(data_dependencies[descriptor.capability_id]),
                    "parallelizable": descriptor.parallelizable,
                    "producesArtifact": descriptor.produces_artifact,
                    "requiresEvidence": descriptor.requires_evidence,
                    "writesMemory": descriptor.writes_memory,
                    # 能力目录只表达“是否值得沉淀”；这里将其降为固定的首期策略，
                    # 供 Runtime 冻结到 WorkflowStep。使用上限指可注入 Agent 上下文
                    # 的记忆条数与内容量，不是模型调用次数或费用额度。
                    "memoryPolicy": {
                        "policyId": f"capability:{descriptor.capability_id}:v1",
                        "read": True,
                        "write": descriptor.writes_memory,
                        "readTypes": ["episodic"],
                        "writeType": "episodic" if descriptor.writes_memory else None,
                        "limit": 10,
                        "tokenBudget": None,
                        "requireAudit": descriptor.writes_memory,
                    },
                    "routerScore": binding.score,
                    "taskPlanKey": plan_key_by_capability[descriptor.capability_id],
                },
            )
            blueprint.nodes.append(step)
            steps.append(step)
            step_by_capability[descriptor.capability_id] = step

            if binding.agent_name not in agent_nodes:
                agent_id = f"agent::{binding.agent_name}"
                agent_nodes[binding.agent_name] = agent_id
                blueprint.nodes.append(
                    AgentNode(
                        nodeId=agent_id,
                        name=binding.agent_name,
                        role=descriptor.display_name,
                        capabilityTags=[descriptor.capability_id],
                        ephemeral=binding.ephemeral,
                    )
                )
            else:
                agent_node = blueprint.get_node(agent_nodes[binding.agent_name])
                if descriptor.capability_id not in agent_node.capability_tags:
                    agent_node.capability_tags.append(descriptor.capability_id)
            blueprint.edges.append(
                ACGEdge(
                    sourceId=agent_nodes[binding.agent_name],
                    targetId=node_id,
                    edgeType=EdgeType.EXECUTION,
                )
            )

            if descriptor.requires_evidence:
                evidence = EvidenceNode(
                    nodeId=f"evidence::{node_id}",
                    name=f"Evidence:{descriptor.display_name}",
                    evidenceType="retrieved",
                    metadata={"producerStepId": node_id, "capabilityId": descriptor.capability_id},
                )
                blueprint.nodes.append(evidence)
                step.evidence_ids.append(evidence.node_id)
            if descriptor.writes_memory:
                memory = MemoryNode(
                    nodeId=f"memory::{node_id}",
                    name=f"Memory:{descriptor.display_name}",
                    memoryType="episodic",
                    metadata={"capabilityId": descriptor.capability_id},
                )
                blueprint.nodes.append(memory)
                blueprint.edges.append(
                    ACGEdge(sourceId=node_id, targetId=memory.node_id, edgeType=EdgeType.WRITE)
                )
                step.memory_ids.append(memory.node_id)

        return steps, step_by_capability

    def _wire_execution_graph(
        self,
        blueprint,
        selected,
        steps,
        step_by_capability,
        descriptors,
        dependencies,
        *,
        enable_parallel_controls: bool,
    ) -> None:
        start = ControlNode(nodeId="ctrl_start", name="START", controlType=ControlType.START)
        end = ControlNode(nodeId="ctrl_end", name="END", controlType=ControlType.END)
        blueprint.nodes.extend([start, end])

        groups: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
        for capability_id in selected:
            descriptor = descriptors[capability_id]
            if descriptor.parallelizable:
                groups[(descriptor.planning_stage, tuple(dependencies[capability_id]))].append(
                    capability_id
                )
        parallel_groups = (
            [items for items in groups.values() if len(items) > 1]
            if enable_parallel_controls
            else []
        )
        group_for = {
            capability_id: group_index
            for group_index, group in enumerate(parallel_groups, start=1)
            for capability_id in group
        }
        controls: dict[int, tuple[ControlNode, ControlNode]] = {}
        for group_index, group in enumerate(parallel_groups, start=1):
            branch_ids = [step_by_capability[item].node_id for item in group]
            join_id = f"ctrl_join_{group_index}"
            parallel = ControlNode(
                nodeId=f"ctrl_parallel_{group_index}",
                name=f"PARALLEL:{descriptors[group[0]].planning_stage}",
                controlType=ControlType.PARALLEL,
                parallelSpec=ParallelSpec(
                    branchEntryIds=branch_ids,
                    joinNodeId=join_id,
                ),
            )
            join = ControlNode(
                nodeId=join_id,
                name=f"JOIN:{descriptors[group[0]].planning_stage}",
                controlType=ControlType.CONSENSUS,
                consensusSpec=ConsensusSpec(
                    participantStepIds=branch_ids,
                    quorum=len(branch_ids),
                    strategy="auditor",
                ),
            )
            controls[group_index] = (parallel, join)
            blueprint.nodes.extend([parallel, join])
            for capability_id in group:
                self._add_dependency(blueprint, parallel.node_id, step_by_capability[capability_id].node_id)
                self._add_dependency(blueprint, step_by_capability[capability_id].node_id, join.node_id)

        wired_groups: set[int] = set()
        for capability_id in selected:
            group_index = group_for.get(capability_id)
            if group_index is not None:
                if group_index in wired_groups:
                    continue
                wired_groups.add(group_index)
                parallel, _ = controls[group_index]
                group_dependencies = dependencies[capability_id]
                if not group_dependencies:
                    self._add_dependency(blueprint, start.node_id, parallel.node_id)
                for dependency in group_dependencies:
                    source = self._execution_source(dependency, group_for, controls, step_by_capability)
                    self._add_dependency(blueprint, source, parallel.node_id)
                continue

            target = step_by_capability[capability_id].node_id
            if not dependencies[capability_id]:
                self._add_dependency(blueprint, start.node_id, target)
            for dependency in dependencies[capability_id]:
                source = self._execution_source(dependency, group_for, controls, step_by_capability)
                self._add_dependency(blueprint, source, target)

        consumed = {dependency for values in dependencies.values() for dependency in values}
        terminal_sources: set[str] = set()
        for capability_id in selected:
            if capability_id in consumed:
                continue
            group_index = group_for.get(capability_id)
            source = (
                controls[group_index][1].node_id
                if group_index is not None
                else step_by_capability[capability_id].node_id
            )
            terminal_sources.add(source)
        for source in terminal_sources:
            self._add_dependency(blueprint, source, end.node_id)

    def _wire_data_contracts(
        self,
        blueprint,
        selected,
        step_by_capability,
        descriptors,
        dependencies,
    ) -> None:
        for target_capability in selected:
            target = step_by_capability[target_capability]
            for source_capability in dependencies[target_capability]:
                source = step_by_capability[source_capability]
                fields = self._output_fields(descriptors[source_capability].output_contract)
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=source.node_id,
                        targetId=target.node_id,
                        edgeType=EdgeType.COMMUNICATION,
                        dataFields=fields,
                        metadata={"mode": "catalog_contract"},
                    )
                )
                if source.evidence_ids:
                    blueprint.edges.append(
                        ACGEdge(
                            sourceId=source.evidence_ids[0],
                            targetId=target.node_id,
                            edgeType=EdgeType.SUPPORT,
                        )
                    )
                if source.memory_ids:
                    blueprint.edges.append(
                        ACGEdge(
                            sourceId=source.memory_ids[0],
                            targetId=target.node_id,
                            edgeType=EdgeType.READ,
                        )
                    )

    def _selected_dependencies(
        self,
        capability_id: str,
        selected: set[str],
        *,
        optional_dependencies: tuple[str, ...] | None,
    ) -> list[str]:
        descriptor = self.capability_catalog.get(capability_id)
        dependencies = list(descriptor.depends_on)
        if optional_dependencies is None:
            dependencies.extend(
                dependency
                for dependency in descriptor.optional_dependencies
                if dependency in selected
            )
        else:
            declared = set(descriptor.optional_dependencies)
            dependencies.extend(
                dependency
                for dependency in optional_dependencies
                if dependency in selected and dependency in declared
            )
        return list(dict.fromkeys(dependency for dependency in dependencies if dependency in selected))

    @staticmethod
    def _minimal_dependencies(dependencies: list[str], all_dependencies: dict[str, list[str]]) -> list[str]:
        def ancestors(capability_id: str) -> set[str]:
            found: set[str] = set()
            pending = list(all_dependencies.get(capability_id, []))
            while pending:
                current = pending.pop()
                if current in found:
                    continue
                found.add(current)
                pending.extend(all_dependencies.get(current, []))
            return found

        return [
            dependency
            for dependency in dependencies
            if not any(
                dependency in ancestors(other)
                for other in dependencies
                if other != dependency
            )
        ]

    @staticmethod
    def _execution_source(dependency, group_for, controls, step_by_capability) -> str:
        group_index = group_for.get(dependency)
        if group_index is not None:
            return controls[group_index][1].node_id
        return step_by_capability[dependency].node_id

    @staticmethod
    def _dependency_node_id(network: CollaborationNetwork, dependency: str) -> str:
        used: set[str] = set()
        for binding in network.bindings:
            node_id = ACGBuilder._step_id(binding.agent_name, binding.capability, used)
            used.add(node_id)
            if binding.capability == dependency:
                return node_id
        raise KeyError(dependency)

    @staticmethod
    def _step_id(agent_name: str, capability_id: str, used_ids: set[str]) -> str:
        base = agent_name.strip() or capability_id.strip() or "step"
        node_id = base
        suffix = 2
        while node_id in used_ids:
            node_id = f"{base}_{suffix}"
            suffix += 1
        return node_id

    @staticmethod
    def _output_fields(contract: dict) -> list[str]:
        required = contract.get("required") if isinstance(contract, dict) else None
        return [str(item) for item in required] if isinstance(required, list) else []

    @staticmethod
    def _add_dependency(blueprint: ACGBlueprint, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            raise ValueError(f"self dependency is not allowed: {source_id}")
        if any(
            edge.source_id == source_id and edge.target_id == target_id
            for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY)
        ):
            return
        blueprint.edges.append(
            ACGEdge(sourceId=source_id, targetId=target_id, edgeType=EdgeType.DEPENDENCY)
        )


__all__ = ["ACGBuilder"]
