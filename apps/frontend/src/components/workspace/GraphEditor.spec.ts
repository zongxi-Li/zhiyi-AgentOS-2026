import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref, shallowRef } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GraphEditor from './GraphEditor.vue'
import GraphVersionToolbar from './GraphVersionToolbar.vue'
import { graphVersionsKey, type GraphVersionsController } from './graphVersions'
import { agentosApi, type GraphProjection, type WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'

const graph: GraphProjection = { graphId: 'graph_1', nodes: [{ nodeId: 'node_1', nodeType: 'step', name: 'Capacity', display: { semanticTaskKey: 'capacity' } }], edges: [] }
const graphNodes: WorkspaceGraphNode[] = [{ acgNodeId: 'node_1', nodeType: 'step', name: 'Capacity', semanticTaskKey: 'capacity', taskId: 'task_1', identityQuality: 'canonical', displayOrder: 0 }]

const topologyCalls = { focusNode: vi.fn(), locateCurrentTask: vi.fn() }
const topologyStub = defineComponent({
  props: ['blueprint', 'focusNodeId', 'workbench', 'runtimePhases', 'stepStates', 'completedStepIds', 'runId'],
  emits: ['nodeSelected', 'nodeDoubleClicked'],
  setup(_props, { expose }) { expose(topologyCalls) },
  template: '<div class="topology-stub"><button @click="$emit(\'nodeSelected\', \'node_1\')">select</button><button @click="$emit(\'nodeDoubleClicked\', \'node_1\')">open</button><button @click="$emit(\'nodeDoubleClicked\', \'unknown\')">unknown</button></div>'
})

const observation = (run: Record<string, unknown> | null, runId = 'run_1'): RuntimeObservation => ({
  runId, run: run as RuntimeObservation['run'], runStatus: run ? 'running' : null,
  traces: [], events: [], communication: [], toolCalls: [], problems: [],
  audit: {} as RuntimeObservation['audit'], provenance: {} as RuntimeObservation['provenance'],
  operational: null, lineage: null, lifecycles: [], recoveryTrace: [], contractViolations: [],
  scheduleTrace: [], patchRefs: []
} as RuntimeObservation)

const observedRun = {
  runId: 'run_1', missionId: 'mission_1', workflowId: 'wf', domain: 'legal', status: 'running',
  steps: [
    { stepId: 'node_1', name: 'Capacity', agentName: 'agent.a', status: 'completed' },
    { stepId: 'node_2', name: 'Check', agentName: 'agent.b', status: 'waiting_review' }
  ],
  completedStepIds: ['node_1'], activeStepIds: ['node_2']
}

const mountEditor = (extraProps: Record<string, unknown> = {}) => mount(GraphEditor, {
  props: { graph, graphNodes, selectedSemanticTaskKey: null, focusNodeId: null, ...extraProps },
  global: { stubs: { AcgTopologyGraph: topologyStub } }
})

const showRuntime = async (wrapper: ReturnType<typeof mountEditor>) => {
  await wrapper.findAll('.graph-editor__modes button')[1].trigger('click')
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(agentosApi, 'getPlanSnapshot').mockResolvedValue({ runId: 'run_1', plan: null })
})
afterEach(() => vi.restoreAllMocks())

describe('GraphEditor', () => {
  it('uses the frozen plan for dependencies and locates a specific runtime node of the same semantic task', async () => {
    const runtimeGraph: GraphProjection = { ...graph, nodes: [...graph.nodes,
      { nodeId: 'expanded_2', nodeType: 'step', name: '补充检查', display: { semanticTaskKey: 'capacity' } }] }
    const task = { objective: '核对输入', rationale: '', acceptanceCriteria: [], sourceRefs: [] }
    const initialPlan = { planVersion: 1, commitId: 'commit-1', commitmentRevision: 1, objective: '分析容量',
      constraints: [], expectedArtifacts: [], tasks: [{ ...task, key: 'capacity', title: '容量', capabilities: ['read'] },
        { ...task, key: 'report', title: '报告' }],
      relations: [{ sourceKey: 'capacity', targetKey: 'report', relationType: 'depends_on' as const }] }
    vi.mocked(agentosApi.getPlanSnapshot).mockResolvedValue({ runId: 'run_1', plan: initialPlan })
    const wrapper = mountEditor({ graph: runtimeGraph, runId: 'run_1', runtimeObservation: observation(observedRun) })
    await flushPromises()
    expect(wrapper.get('.graph-editor__modes button[aria-pressed="true"]').text()).toBe('规划图 ACG')
    expect(agentosApi.getPlanSnapshot).toHaveBeenCalledWith('run_1', null, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findComponent(topologyStub).props('blueprint').edges).toMatchObject([{ sourceId: 'capacity', targetId: 'report' }])
    expect(wrapper.findComponent(topologyStub).props('stepStates')).toBeUndefined()
    expect(wrapper.text()).toContain('所需能力：read')
    const links = wrapper.findAll('.planning-graph__links button')
    expect(links).toHaveLength(2)
    await links[1].trigger('click')
    expect(wrapper.findComponent(topologyStub).props('blueprint')).toEqual(runtimeGraph)
    expect(topologyCalls.focusNode).toHaveBeenCalledWith('expanded_2')
    await wrapper.findAll('.graph-editor__modes button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('所需能力：read')
    expect(agentosApi.getPlanSnapshot).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('renders only one canvas state while a historical snapshot loads, fails and recovers', async () => {
    const displayGraph = shallowRef<GraphProjection | null>(null)
    const snapshotLoading = ref(true)
    const snapshotError = ref('')
    const versions = { displayGraph, snapshotLoading, snapshotError,
      historical: ref(true), following: ref(false), selectedKey: ref('historical-v1'), selected: ref(null), previous: ref(null), comparing: ref(false),
      difference: ref(null), previousGraph: ref(null) } as unknown as GraphVersionsController
    const wrapper = mount(GraphEditor, {
      props: { graph, graphNodes, selectedSemanticTaskKey: null, focusNodeId: null },
      global: { provide: { [graphVersionsKey as symbol]: versions },
        stubs: { AcgTopologyGraph: topologyStub, GraphVersionToolbar: true } }
    })
    await showRuntime(wrapper)
    expect(wrapper.findComponent(topologyStub).exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载图快照')
    expect(wrapper.get('[role="status"]').text()).not.toContain('没有可展示')
    snapshotLoading.value = false
    snapshotError.value = '图快照加载失败，请重试'
    await nextTick()
    expect(wrapper.findComponent(topologyStub).exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('图快照加载失败，请重试')
    displayGraph.value = graph
    snapshotError.value = ''
    await nextTick()
    expect(wrapper.findComponent(topologyStub).props('blueprint')).toEqual(graph)
    expect(wrapper.find('.graph-editor__empty').exists()).toBe(false)
    wrapper.unmount()
  })
  it('shows the current recovery message while cleanup is active and clears it when execution resumes', async () => {
    const message = '节点执行失败，正在停止并行执行并等待清理'
    const run = { ...observedRun, lifecyclePhase: 'recovery', lifecycleMessage: message,
      activeStepIds: ['node_1'], steps: observedRun.steps.map(step => ({ ...step, status: 'failed' })) }
    const wrapper = mountEditor({ runId: 'run_1', runtimeObservation: observation(run) })
    await showRuntime(wrapper)
    expect(wrapper.get('.graph-editor__runtime').text()).toContain(message)
    expect(wrapper.get('.graph-editor__runtime').text()).not.toContain('当前执行')
    expect(wrapper.get('.graph-editor__runtime button').text()).toBe('定位当前节点')
    await wrapper.setProps({ runtimeObservation: observation({ ...run, lifecyclePhase: 'executing' }) })
    expect(wrapper.get('.graph-editor__runtime').text()).toContain('当前执行')
    expect(wrapper.get('.graph-editor__runtime').text()).not.toContain(message)
  })
  it('locates the active execution on every click even when external selection stays unchanged', async () => {
    const wrapper = mountEditor({ runId: 'run_1', focusNodeId: 'node_1',
      graph: { ...graph, nodes: [...graph.nodes, { nodeId: 'node_2', nodeType: 'step', name: '补读剩余范围' }] },
      runtimeObservation: observation(observedRun) })
    await showRuntime(wrapper)
    expect(wrapper.get('.graph-editor__runtime').text()).toContain('补读剩余范围')
    await wrapper.get('.graph-editor__runtime button').trigger('click')
    await wrapper.get('.graph-editor__runtime button').trigger('click')
    expect(topologyCalls.locateCurrentTask).toHaveBeenCalledTimes(2)
    expect(wrapper.findComponent(topologyStub).props('focusNodeId')).toBe('node_1')
  })
  it('locates a comparison node again when the same change is clicked repeatedly', async () => {
    const wrapper = mountEditor()
    await showRuntime(wrapper)
    const toolbar = wrapper.findComponent(GraphVersionToolbar)
    toolbar.vm.$emit('locateNode', 'node_1')
    toolbar.vm.$emit('locateNode', 'node_1')
    expect(topologyCalls.focusNode.mock.calls).toEqual([['node_1'], ['node_1']])
    expect(wrapper.findComponent(topologyStub).props('focusNodeId')).toBeNull()
  })
  it('keeps the failed current step visible when execution stops and clears it for a different run', async () => {
    const currentGraph = { ...graph, nodes: [...graph.nodes, { nodeId: 'node_2', nodeType: 'step', name: '审查读取证据' }] }
    const wrapper = mountEditor({ graph: currentGraph, runId: 'run_1', runtimeObservation: observation(observedRun) })
    await showRuntime(wrapper)
    expect(wrapper.get('.graph-editor__runtime').text()).toContain('当前执行 · 审查读取证据')
    await wrapper.setProps({ runtimeObservation: observation({ ...observedRun, status: 'failed',
      activeStepIds: [], currentStepId: 'node_2',
      steps: observedRun.steps.map(step => ({ ...step, status: 'failed' })) }) })
    expect(wrapper.get('.graph-editor__runtime').classes()).toContain('is-failed')
    expect(wrapper.get('.graph-editor__runtime').text()).toContain('执行受阻 · 审查读取证据')
    expect(wrapper.get('.graph-editor__runtime button').text()).toBe('定位失败节点')
    await wrapper.get('.graph-editor__runtime button').trigger('click')
    expect(topologyCalls.focusNode).toHaveBeenCalledWith('node_2')
    expect(topologyCalls.locateCurrentTask).not.toHaveBeenCalled()
    await wrapper.setProps({ runId: 'run_other' })
    expect(wrapper.find('.graph-editor__runtime').exists()).toBe(false)
  })
  it('maps node selection to semanticTaskKey', async () => {
    const wrapper = mountEditor()
    await showRuntime(wrapper)
    await wrapper.get('.topology-stub button').trigger('click')
    expect(wrapper.emitted('selectSemanticTask')).toEqual([['capacity']])
  })

  it('maps node double click to semanticTaskKey for the parent choice flow', async () => {
    const wrapper = mountEditor()
    await showRuntime(wrapper)
    await wrapper.findAll('.topology-stub button')[1].trigger('click')
    expect(wrapper.emitted('openSemanticTask')).toEqual([['capacity']])
  })

  it('does not guess a semantic key for an unbound graph node', async () => {
    const wrapper = mountEditor()
    await showRuntime(wrapper)
    await wrapper.findAll('.topology-stub button')[2].trigger('click')
    expect(wrapper.emitted('openSemanticTask')).toEqual([[null]])
  })

  it('passes persisted step states of the observed run to the topology graph', async () => {
    const wrapper = mountEditor({ runId: 'run_1', runtimeObservation: observation(observedRun) })
    await showRuntime(wrapper)
    const stub = wrapper.findComponent(topologyStub)
    expect(stub.props('stepStates').map((state: { stepId: string; status: string }) => [state.stepId, state.status]))
      .toEqual([['node_1', 'completed'], ['node_2', 'waiting_review']])
    expect(stub.props('completedStepIds')).toEqual(['node_1'])
  })

  it('ignores runtime observation of a different run', async () => {
    const wrapper = mountEditor({ runId: 'run_1', runtimeObservation: observation({ ...observedRun, runId: 'run_other' }, 'run_other') })
    await showRuntime(wrapper)
    const stub = wrapper.findComponent(topologyStub)
    expect(stub.props('stepStates')).toEqual([])
    expect(stub.props('completedStepIds')).toEqual([])
  })
})
