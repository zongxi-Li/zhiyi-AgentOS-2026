"""Semantic revisions preserve frozen context contracts on retained edges."""
from types import SimpleNamespace

from components.planner.semantic_patch_planning import _rebuild_resource_plan
from support.acg.planning import ACGResourcePlan, CommunicationSpec, EvidenceSpec, MemoryAccessSpec


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


def test_removed_dependency_drops_its_context_contracts_without_rewriting_producer():
    current = ACGResourcePlan(communication=(CommunicationSpec(producerStepId='A', consumerStepId='B', channel='A:B'),),
        memory=(MemoryAccessSpec(stepId='A', memoryId='memo', access='write'),
                MemoryAccessSpec(stepId='B', memoryId='memo', access='read')),
        evidence=(EvidenceSpec(evidenceId='fact', producerStepId='A', consumerStepIds=('B',), source='workflow'),))
    next_resources = rebuild(current, dependencies={'B': [], 'C': []})
    assert next_resources.communication == ()
    assert next_resources.memory == (current.memory[0],)
    assert next_resources.evidence == (current.evidence[0].model_copy(update={'consumer_step_ids': ()}),)
