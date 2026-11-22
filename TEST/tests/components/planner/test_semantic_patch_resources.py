"""Semantic revisions preserve frozen context contracts on retained edges."""
from types import SimpleNamespace

from components.planner.semantic_patch_planning import _rebuild_resource_plan
from contracts.acg.planning import ACGResourcePlan, CommunicationSpec, EvidenceSpec, MemoryAccessSpec


def rebuild(current, *, dependencies=None, changed=False):
    return _rebuild_resource_plan(current=current, previous_dependencies={('A', 'B')},
        retained_step_ids={'A', 'B'}, changed_keys={'C'} if changed else set(),
        node_id_by_task={key: key for key in 'ABC'}, dependencies=dependencies or {'B': ['A']},
        descriptors={'C': SimpleNamespace(writes_memory=False, requires_evidence=False, model_demand=None,
                                          capability_id='analysis', display_name='Analysis')},
        routed={'C': SimpleNamespace(logical_agent_id='agent:test', ephemeral=False)},
        output_contracts={key: {'type': 'object', 'properties': {'finding': {'type': 'string'}}} for key in 'ABC'})


def test_implicit_result_pull_stays_implicit_when_unrelated_work_is_added():
    current = ACGResourcePlan(memory=(MemoryAccessSpec(stepId='A', memoryId='memo', access='write'),),
        evidence=(EvidenceSpec(evidenceId='fact', producerStepId='A', source='workflow'),))
    next_resources = rebuild(current, dependencies={'B': ['A'], 'C': ['A']}, changed=True)
    assert [(item.producer_step_id, item.consumer_step_id) for item in next_resources.communication] == [('A', 'C')]
    assert next_resources.communication[0].allowed_fields == ('finding',)
    assert [(item.step_id, item.access) for item in next_resources.memory] == [('A', 'write'), ('C', 'read')]
    assert next_resources.evidence[0].consumer_step_ids == ('C',)


def test_explicit_channels_memory_and_evidence_retain_every_frozen_field():
    current = ACGResourcePlan(communication=(CommunicationSpec(producerStepId='A', consumerStepId='B',
        channel='frozen-channel', allowedFields=('authorized',), maxTokens=97,
        schemaHash='frozen', backlogLimit=7, partition='frozen-partition'),),
        memory=(MemoryAccessSpec(stepId='A', memoryId='memo', access='write'),
                MemoryAccessSpec(stepId='B', memoryId='memo', access='read', memoryType='episodic',
                                 retentionPolicy='mission', schema={'allowed': True})),
        evidence=(EvidenceSpec(evidenceId='fact', producerStepId='A', consumerStepIds=('B',),
                               source='workflow', schema={'type': 'object'}),))
    assert rebuild(current) == current


def test_new_consumer_gets_optional_fields_without_expanding_a_retained_channel():
    current = ACGResourcePlan(communication=(CommunicationSpec(producerStepId='A', consumerStepId='B',
        channel='frozen-restricted', allowedFields=('legacy_required',)),))
    frozen = current.model_dump(by_alias=True, mode='json')
    revised = rebuild(current, dependencies={'B': ['A'], 'C': ['A']}, changed=True)
    retained, added = revised.communication
    assert retained == current.communication[0]
    assert added.producer_step_id == 'A' and added.consumer_step_id == 'C'
    assert added.allowed_fields == ('finding',)
    assert current.model_dump(by_alias=True, mode='json') == frozen


def test_incremental_lowering_uses_frozen_producer_schema_for_new_consumer(monkeypatch):
    from components.executor.compiler import ACGGraphCompiler
    from components.planner.acg_lowerer import ACGLowerer
    from components.planner.cognitive_router import CognitiveRouter
    from components.planner.semantic_patch_planning import build_semantic_patch_lowering_input
    from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan, TaskPlanRelation
    from support.capabilities import CapabilityCatalog, ContextConsumptionPolicy, PlanningCapabilityDescriptor
    from contracts.acg.planning import AgentBindingSpec
    from contracts.acg.schema import ACGEdge, RuntimeBlueprintSpec, StepNode

    mission = 'mission_0123456789ab'
    source_contract = {'type': 'object', 'properties': {'analysis': {}, 'sources': {}, 'notes': {}},
                       'required': ['analysis']}
    old_input = {'from': {'A': ['analysis']}, 'schema': {}}
    old_channel = CommunicationSpec(producerStepId='A', consumerStepId='B', channel='frozen',
                                    allowedFields=('analysis',))
    blueprint = RuntimeBlueprintSpec(graphId='graph', missionId=mission, nodes=[
        StepNode(nodeId='A', name='Source', capability='producer', outputSpec=source_contract,
                 metadata={'taskPlanKey': 'source'}),
        StepNode(nodeId='B', name='Existing', capability='consumer', inputSpec=old_input,
                 metadata={'taskPlanKey': 'existing'})],
        edges=[ACGEdge(edgeId='A:B', sourceId='A', targetId='B', edgeType='dependency')],
        resourcePlan=ACGResourcePlan(communication=(old_channel,), bindings=tuple(
            AgentBindingSpec(stepId=node, plannedAgentId='agent:test') for node in ('A', 'B'))))
    tasks = tuple(PlannedTask(key=key, title=key, objective=key, capabilityRequirements=(capability,))
                  for key, capability in [('source', 'producer'), ('existing', 'consumer')])
    current = TaskPlan(missionId=mission, nodes=tasks, relations=(
        TaskPlanRelation(sourceKey='source', targetKey='existing', relationType='depends_on'),))
    next_plan = current.model_copy(update={'plan_version': 2, 'nodes': (*tasks,
        PlannedTask(key='new', title='New', objective='Use prior findings', capabilityRequirements=('consumer',))),
        'relations': (*current.relations,
            TaskPlanRelation(sourceKey='source', targetKey='new', relationType='depends_on'))})
    # A current catalog change must not replace a retained producer's schema.
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId='producer', displayName='Producer',
            outputContract={'properties': {'new_catalog_field': {}}}),
        PlanningCapabilityDescriptor(capabilityId='consumer', displayName='Consumer',
            inputContract={'type': 'object', 'properties': {'analysis': {}}, 'required': ['analysis']},
            contextPolicy=ContextConsumptionPolicy(supplementalReadBudget={'version': 'supplemental-read.v1'}))])
    monkeypatch.setattr(CognitiveRouter, 'candidates_for', lambda *args, **kwargs: [
        SimpleNamespace(logical_agent_id='agent:test', score=1, ephemeral=False)])
    original = blueprint.model_dump(by_alias=True, mode='json')
    lowering = build_semantic_patch_lowering_input(blueprint=blueprint, current_plan=current,
        next_plan=next_plan, base_bindings=tuple(TaskImplementationBinding(planNodeKey=key, acgNodeId=node)
            for key, node in [('source', 'A'), ('existing', 'B')]), changed_keys={'new'},
        capability_catalog=catalog, agent_registry=object(), domain='general')
    steps = {step.task_key: step for step in lowering.steps}
    assert steps['source'].output_spec == source_contract
    assert steps['existing'].input_spec == old_input
    assert steps['new'].input_spec['from'] == {'A': ['analysis', 'notes', 'sources']}
    assert steps['new'].input_spec['prefetch'] == {'A': ['analysis', 'sources']}
    revised = ACGLowerer().lower(lowering)
    package = ACGGraphCompiler().compile_package(revised, run_id='run')
    rules = {rule.consumer_step_id: rule for rule in package.communication_manifest.rules}
    assert rules['B'].allowed_fields == ('analysis',)
    assert rules[steps['new'].node_id].allowed_fields == ('analysis', 'notes', 'sources')
    assert blueprint.model_dump(by_alias=True, mode='json') == original


def test_removed_dependency_drops_its_context_contracts_without_rewriting_producer():
    current = ACGResourcePlan(communication=(CommunicationSpec(producerStepId='A', consumerStepId='B', channel='A:B'),),
        memory=(MemoryAccessSpec(stepId='A', memoryId='memo', access='write'),
                MemoryAccessSpec(stepId='B', memoryId='memo', access='read')),
        evidence=(EvidenceSpec(evidenceId='fact', producerStepId='A', consumerStepIds=('B',), source='workflow'),))
    next_resources = rebuild(current, dependencies={'B': [], 'C': []})
    assert next_resources.communication == ()
    assert next_resources.memory == (current.memory[0],)
    assert next_resources.evidence == (current.evidence[0].model_copy(update={'consumer_step_ids': ()}),)
