"""根据目录描述符和已解析绑定构造通用 ACG 图。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from contracts.planning import SemanticTaskRelationType, TaskImplementationBinding, TaskPlan
from support.acg.models import (
    ACGBlueprint,
    ACGEdge,
    AgentNode,
    ControlNode,
    ControlType,
    ConditionOperator,
    ConditionSpec,
    EdgeType,
    EvidenceNode,
    MemoryNode,
    ParallelSpec,
    LoopSpec,
    ConsensusSpec,
    StepNode,
    validate_blueprint,
    promote_workflow_to_acg,
)
from support.acg.models import CapabilityCatalog
from .cognitive_router import CollaborationNetwork
from .acg_semantic_validator import (
    validate_acg_semantic_preservation,
    validate_bound_acg_semantics,
)
from support.acg.models import build_default_capability_catalog
from support.acg.models import TaskSemanticProfile

if TYPE_CHECKING:
    from .algorithms import PlanningVariant


@dataclass(frozen=True)
class ACGBuildResult:
    blueprint: ACGBlueprint
    bindings: tuple[TaskImplementationBinding, ...]


class ACGBuilder:
    """依据能力描述符的依赖与合同构造单个可执行 ACG 图。"""

    def __init__(self, capability_catalog: CapabilityCatalog | None = None) -> None:
        self.capability_catalog = capability_catalog or build_default_capability_catalog()

    def build(
        self,
        *,
        mission_id: str,
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
        if task_plan.mission_id != mission_id:
            raise ValueError("TaskPlan missionId does not match ACG build Mission")
        if any(len(node.capability_requirements) != 1 for node in task_plan.nodes):
            raise ValueError("Every executable TaskPlan node must select exactly one capability")
        selected_capabilities = {binding.capability for binding in network.bindings}
        planned_capabilities = {
            str(node.capability_requirements[0]) for node in task_plan.nodes
        }
        if not planned_capabilities <= selected_capabilities:
            missing = sorted(planned_capabilities - selected_capabilities)
            raise ValueError(
                "TaskPlan capabilities lack an Agent binding: "
                f"missing={','.join(missing)}; "
                f"planned={','.join(sorted(planned_capabilities))}; "
                f"bound={','.join(sorted(selected_capabilities))}"
            )

        blueprint = ACGBlueprint(
            missionId=mission_id,
            objective=profile.primary_goal,
            complexityLevel=profile.estimated_complexity,
            metadata={
                "generatedBy": "generic_acg_builder",
                "domainHint": profile.domain_hint,
                "entropyBudget": profile.entropy_budget,
                "estimatedEntropy": network.estimated_entropy,
                "expectedArtifacts": list(task_plan.expected_artifacts),
            },
        )
        if variant is not None:
            blueprint.metadata["planningVariantId"] = variant.variant_id
        selected = [node.key for node in task_plan.nodes]
        descriptors = {
            node.key: self.capability_catalog.get(node.capability_requirements[0])
            for node in task_plan.nodes
        }
        data_dependencies = {key: [] for key in selected}
        for relation in task_plan.relations:
            if relation.relation_type == SemanticTaskRelationType.DEPENDS_ON:
                data_dependencies[relation.target_key].append(relation.source_key)
        control_dependencies = {
            task_key: self._minimal_dependencies(
                data_dependencies[task_key],
                data_dependencies,
            )
            for task_key in selected
        }

        steps, step_by_capability = self._build_steps(
            blueprint,
            network,
            task_plan,
            descriptors,
            data_dependencies,
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
        self._wire_control_policies(blueprint, task_plan, step_by_capability)
        blueprint.touch()
        validate_blueprint(blueprint)
        validate_acg_semantic_preservation(task_plan, blueprint)
        validate_bound_acg_semantics(
            task_plan,
            blueprint,
            tuple(TaskImplementationBinding(
                planNodeKey=step.metadata["taskPlanKey"], acgNodeId=step.node_id,
            ) for step in steps),
            require_exact=True,
        )
        return blueprint

    def build_template(self, *, workflow, task_plan: TaskPlan) -> ACGBuildResult:
        """Promote an execution template and bind it to declared Planner semantics."""
        blueprint = promote_workflow_to_acg(
            workflow, mission_id=task_plan.mission_id, infer_dependencies=False,
        )
        plan_keys = {node.key for node in task_plan.nodes}
        steps = blueprint.step_nodes()
        if len(steps) == 1 and len(plan_keys) == 1:
            steps[0].metadata["taskPlanKey"] = next(iter(plan_keys))
        else:
            for step in steps:
                step.metadata["taskPlanKey"] = f"step:{step.node_id}"
        step_by_key = {step.metadata["taskPlanKey"]: step for step in steps}
        if len(step_by_key) != len(steps) or set(step_by_key) != plan_keys:
            raise ValueError("Template Steps must bind exactly to TaskPlan nodes")

        plan_adjacency: dict[str, list[str]] = {}
        for relation in task_plan.relations:
            if relation.relation_type is SemanticTaskRelationType.DEPENDS_ON:
                plan_adjacency.setdefault(relation.source_key, []).append(relation.target_key)
                self._add_dependency(
                    blueprint,
                    step_by_key[relation.source_key].node_id,
                    step_by_key[relation.target_key].node_id,
                )

        def authorized_order(source_key: str, target_key: str) -> bool:
            pending = [source_key]
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == target_key:
                    return True
                if current not in visited:
                    visited.add(current)
                    pending.extend(plan_adjacency.get(current, ()))
            return False

        key_by_step_id = {step.node_id: key for key, step in step_by_key.items()}
        for definition in workflow.steps:
            target_id = definition.next_step_id
            if target_id in (None, "", "done", "completed"):
                continue
            if target_id not in key_by_step_id or not authorized_order(
                key_by_step_id[definition.step_id], key_by_step_id[target_id],
            ):
                raise ValueError(
                    "Template nextStepId requires a TaskPlan semantic dependency: "
                    f"{definition.step_id} -> {target_id}"
                )
        for edge in blueprint.edges_of_type(EdgeType.COMMUNICATION):
            if edge.metadata.get("contract") != "input.from":
                continue
            if not authorized_order(
                key_by_step_id[edge.source_id], key_by_step_id[edge.target_id],
            ):
                raise ValueError(
                    "Template input.from requires a TaskPlan semantic dependency: "
                    f"{edge.source_id} -> {edge.target_id}"
                )
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
        plan_keys = {node.key for node in task_plan.nodes}
        if len(steps) == 1 and not steps[0].metadata.get("taskPlanKey"):
            steps[0].metadata["taskPlanKey"] = next(iter(plan_keys))
        for step in steps:
            if not step.metadata.get("taskPlanKey") and f"step:{step.node_id}" in plan_keys:
                step.metadata["taskPlanKey"] = f"step:{step.node_id}"
        bindings = tuple(
            TaskImplementationBinding(
                planNodeKey=step.metadata["taskPlanKey"],
                acgNodeId=step.node_id,
            )
            for step in steps
            if step.metadata.get("taskPlanKey") in plan_keys
        )
        if len(bindings) != len(steps) or {item.plan_node_key for item in bindings} != plan_keys:
            raise ValueError(
                "Blueprint requires explicit, unique taskPlanKey bindings for every Step"
            )
        validate_acg_semantic_preservation(task_plan, blueprint)
        validate_bound_acg_semantics(task_plan, blueprint, bindings, require_exact=True)
        return ACGBuildResult(blueprint=blueprint, bindings=bindings)

    def _build_steps(
        self,
        blueprint,
        network,
        task_plan,
        descriptors,
        data_dependencies,
    ) -> tuple[list[StepNode], dict[str, StepNode]]:
        used_ids: set[str] = set()
        agent_nodes: dict[str, str] = {}
        steps: list[StepNode] = []
        step_by_capability: dict[str, StepNode] = {}
        binding_by_capability = {binding.capability: binding for binding in network.bindings}
        node_id_by_task: dict[str, str] = {}
        for task in task_plan.nodes:
            capability = task.capability_requirements[0]
            binding = binding_by_capability[capability]
            node_id = self._step_id(binding.agent_name, capability, used_ids)
            used_ids.add(node_id)
            node_id_by_task[task.key] = node_id

        for task in task_plan.nodes:
            descriptor = descriptors[task.key]
            binding = binding_by_capability[descriptor.capability_id]
            node_id = node_id_by_task[task.key]
            from_map = {
                node_id_by_task[dependency]: self._output_fields(
                    descriptors[dependency].output_contract
                )
                for dependency in data_dependencies[task.key]
            }
            input_spec = dict(descriptor.input_contract)
            if task.workset is not None:
                input_spec = {
                    **input_spec,
                    "workset": task.workset.model_dump(by_alias=True, mode="json"),
                }
            if from_map:
                input_spec = {
                    "from": from_map,
                    "schema": dict(descriptor.input_contract),
                    **(
                        {"workset": task.workset.model_dump(by_alias=True, mode="json")}
                        if task.workset is not None
                        else {}
                    ),
                }
            step = StepNode(
                nodeId=node_id,
                name=task.title,
                goal=task.objective,
                acceptanceCriteria=list(task.acceptance_criteria),
                sourceRefs=list(task.source_refs),
                logicalRole=task.logical_role,
                agentName=binding.agent_name,
                capability=descriptor.capability_id,
                inputSpec=input_spec,
                outputSpec=dict(descriptor.output_contract),
                reviewRequired=descriptor.requires_review,
                metadata={
                    "capabilityId": descriptor.capability_id,
                    "planningStage": descriptor.planning_stage,
                    "role": descriptor.planning_stage,
                    "dependsOn": list(data_dependencies[task.key]),
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
                    "taskPlanKey": task.key,
                    "expectedArtifacts": list(task_plan.expected_artifacts),
                    "producedArtifacts": list(task.produced_artifacts),
                    "decompositionRationale": task.decomposition_rationale,
                    "workset": (
                        task.workset.model_dump(by_alias=True, mode="json")
                        if task.workset is not None
                        else None
                    ),
                    "capabilityPromptProfileVersion": descriptor.prompt_profile.prompt_profile_version,
                    "reasoningEffort": self._reasoning_effort(task, descriptor),
                    "reasoningPolicyReason": self._reasoning_policy_reason(task, descriptor),
                },
            )
            blueprint.nodes.append(step)
            steps.append(step)
            step_by_capability[task.key] = step

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
                    producerStepId=node_id,
                    metadata={"producerStepId": node_id, "capabilityId": descriptor.capability_id},
                )
                blueprint.nodes.append(evidence)
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

    @staticmethod
    def _reasoning_effort(task, descriptor) -> str:
        explicit = str(task.metadata.get("reasoningEffort") or "").strip().lower()
        if explicit in {"low", "high", "max"}:
            return explicit
        capability = descriptor.capability_id
        role = str(task.logical_role or "").strip().lower()
        if (
            descriptor.risk_level_hint in {"high", "critical"}
            or descriptor.requires_review
            or descriptor.produces_artifact
            or role in {"decision", "review", "verification", "join", "sink", "final"}
            or capability in {
                "solution_design", "comparative_analysis", "verification",
                "artifact_generation", "industrial_safety_analysis",
                "industrial_acceptance_validation",
            }
        ):
            return "max"
        if capability in {"information_extraction", "information_retrieval"}:
            return "low"
        return "high"

    @staticmethod
    def _reasoning_policy_reason(task, descriptor) -> str:
        if str(task.metadata.get("reasoningEffort") or "").strip().lower() in {"low", "high", "max"}:
            return "task_plan_explicit"
        if descriptor.risk_level_hint in {"high", "critical"} or descriptor.requires_review:
            return "risk_or_review_critical"
        if descriptor.produces_artifact or str(task.logical_role or "").strip().lower() in {
            "decision", "review", "verification", "join", "sink", "final",
        }:
            return "topology_or_delivery_critical"
        if descriptor.capability_id in {"information_extraction", "information_retrieval"}:
            return "bounded_retrieval_or_extraction"
        return "analytical_default"

    def _wire_control_policies(self, blueprint, task_plan, step_by_key) -> None:
        for index, policy in enumerate(task_plan.control_policies, start=1):
            entry = step_by_key[policy.body_entry_key].node_id
            exit_id = step_by_key[policy.body_exit_key].node_id
            source = step_by_key[policy.condition_source_key].node_id
            control_id = f"ctrl_verification_loop_{index}"
            edge = ACGEdge(
                sourceId=control_id,
                targetId=entry,
                edgeType=EdgeType.CONTROL_FLOW,
            )
            cases = {value: edge.edge_id for value in policy.repeat_values}
            blueprint.nodes.append(
                ControlNode(
                    nodeId=control_id,
                    name="VERIFICATION_LOOP",
                    controlType=ControlType.LOOP,
                    loopSpec=LoopSpec(
                        bodyEntryId=entry,
                        bodyExitId=exit_id,
                        condition=ConditionSpec(
                            sourceNodeId=source,
                            jsonPointer=policy.status_pointer,
                            operator=ConditionOperator.IN,
                            cases=cases,
                        ),
                        # Runtime counts the initial pass as iteration zero.
                        maxIterations=policy.max_revisions + 1,
                        onLimit=("review" if policy.on_exhausted == "human_review" else "fail"),
                    ),
                    metadata={
                        "taskPlanPolicy": "verification_loop",
                        "maxRevisions": policy.max_revisions,
                    },
                )
            )
            blueprint.edges.append(edge)

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
                    source = self._execution_source(dependency, step_by_capability)
                    self._add_dependency(blueprint, source, parallel.node_id)
                continue

            target = step_by_capability[capability_id].node_id
            if not dependencies[capability_id]:
                self._add_dependency(blueprint, start.node_id, target)
            for dependency in dependencies[capability_id]:
                source = self._execution_source(dependency, step_by_capability)
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
        evidence_by_producer = {
            node.producer_step_id: node.node_id
            for node in blueprint.nodes
            if isinstance(node, EvidenceNode) and node.producer_step_id
        }
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
                source_evidence_id = evidence_by_producer.get(source.node_id)
                if source_evidence_id:
                    blueprint.edges.append(
                        ACGEdge(
                            sourceId=source_evidence_id,
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
    def _execution_source(dependency, step_by_capability) -> str:
        # A shared JOIN would make every sibling precede the consumer, including
        # siblings absent from its TaskPlan dependencies.
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
