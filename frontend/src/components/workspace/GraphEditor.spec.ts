import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GraphEditor from './GraphEditor.vue'
import type { AcgBlueprint, WorkspaceGraphNode } from '@/services/api/agentos'

const graph: AcgBlueprint = { graphId: 'graph_1', nodes: [{ nodeId: 'node_1', nodeType: 'step', name: 'Capacity' }], edges: [] }
const graphNodes: WorkspaceGraphNode[] = [{ acgNodeId: 'node_1', nodeType: 'step', name: 'Capacity', semanticTaskKey: 'capacity', taskId: 'task_1', identityQuality: 'canonical', displayOrder: 0 }]

const topologyStub = {
  props: ['blueprint', 'focusNodeId', 'workbench'],
  emits: ['nodeSelected', 'nodeDoubleClicked'],
  template: '<div class="topology-stub"><button @click="$emit(\'nodeSelected\', \'node_1\')">select</button><button @click="$emit(\'nodeDoubleClicked\', \'node_1\')">open</button><button @click="$emit(\'nodeDoubleClicked\', \'unknown\')">unknown</button></div>'
}

const mountEditor = () => mount(GraphEditor, {
  props: { graph, graphNodes, selectedSemanticTaskKey: null, focusNodeId: null },
  global: { stubs: { AcgTopologyGraph: topologyStub } }
})

describe('GraphEditor', () => {
  it('maps node selection to semanticTaskKey', async () => {
    const wrapper = mountEditor()
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('selectSemanticTask')).toEqual([['capacity']])
  })

  it('maps node double click to semanticTaskKey for the parent choice flow', async () => {
    const wrapper = mountEditor()
    await wrapper.findAll('button')[1].trigger('click')
    expect(wrapper.emitted('openSemanticTask')).toEqual([['capacity']])
  })

  it('does not guess a semantic key for an unbound graph node', async () => {
    const wrapper = mountEditor()
    await wrapper.findAll('button')[2].trigger('click')
    expect(wrapper.emitted('openSemanticTask')).toEqual([[null]])
  })
})
