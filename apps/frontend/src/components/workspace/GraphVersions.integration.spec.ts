import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, effectScope, h, nextTick, provide, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GraphEditor from './GraphEditor.vue'
import WorkspaceExplorer from './WorkspaceExplorer.vue'
import { createGraphVersions, graphVersionsKey } from './graphVersions'
import { agentosApi } from '@/services/api/agentos'
import type { GraphProjection, GraphVersionEntry, GraphVersionHistory, MissionWorkspaceProjection, WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'

const graph = (version: number, graphId = 'graph'): GraphProjection => ({ graphId, graphVersion: version,
  nodes: [{ nodeId: 'read', nodeType: 'step', name: '读取证据' },
    version === 1 ? { nodeId: 'removed', nodeType: 'step', name: '旧分析' }
      : { nodeId: 'review', nodeType: 'step', name: '复核证据' }],
  edges: [{ edgeId: version === 1 ? 'old-edge' : 'new-edge', sourceId: 'read',
    targetId: version === 1 ? 'removed' : 'review', edgeType: 'dependency' }] })
const entry = (version: number, current = false, graphId = 'graph'): GraphVersionEntry => ({
  blueprintId: `${graphId}-bp${version}`, graphId, graphVersion: version, current,
  status: current ? 'active' : 'historical', createdAt: '2026-11-17T03:10:00Z',
  predecessorBlueprintId: version === 1 ? null : `${graphId}-bp${version - 1}`,
  reason: version === 1 ? '初始审查计划' : '补充读取后再次复核', patch: null,
  inherited: { completedStepIds: ['read'], skippedStepIds: [], attemptIds: ['attempt-read'], outputRefs: { read: 'output-read' } },
})
const history = (runId = 'run', graphId = 'graph'): GraphVersionHistory => ({ runId, graphId,
  currentBlueprintId: `${graphId}-bp2`, currentGraphVersion: 2,
  items: [entry(1, false, graphId), entry(2, true, graphId)] })
const graphNodes: WorkspaceGraphNode[] = ['read', 'review', 'removed'].map((id, displayOrder) => ({
  acgNodeId: id, nodeType: 'step', name: id, semanticTaskKey: `task:${id}`, taskId: `identity-${id}`,
  identityQuality: 'canonical', displayOrder,
}))
const observation = (runId = 'run'): RuntimeObservation => ({ runId, run: {
  runId, missionId: 'mission', workflowId: 'flow', domain: 'general', status: 'running', graphVersion: 2,
  steps: [{ stepId: 'read', name: '读取', agentName: 'agent', status: 'completed' },
    { stepId: 'review', name: '复核', agentName: 'agent', status: 'running' }],
  completedStepIds: ['read'], activeStepIds: ['review'],
}, traces: [], events: [], communication: [], toolCalls: [], problems: [], audit: {}, provenance: {},
  operational: null, lineage: null, lifecycles: [], recoveryTrace: [], contractViolations: [],
  scheduleTrace: [], patchRefs: [] } as unknown as RuntimeObservation)
const projection = (): MissionWorkspaceProjection => ({
  mission: { missionId: 'mission', userId: 'owner', goal: '审查仓库', description: '', metadata: {},
    createdAt: '2026-11-17T00:00:00Z', updatedAt: '2026-11-17T00:00:00Z', status: 'created' },
  activeRun: { runId: 'run', status: 'running', createdAt: '2026-11-17T00:00:00Z', isActive: true },
  runs: [], graphNodes, diagnostics: [], entries: [
    { entryId: 'graph', kind: 'graph', name: 'graph.acg', group: 'overview', displayOrder: 0 },
    { entryId: 'task:read', kind: 'task', name: '读取', group: 'steps', displayOrder: 0, semanticTaskKey: 'task:read' },
  ],
})
const topologyCalls = { focusNode: vi.fn(), locateCurrentTask: vi.fn() }
const topologyStub = defineComponent({ name: 'AcgTopologyGraph',
  props: ['blueprint', 'focusNodeId', 'runtimePhases', 'stepStates', 'completedStepIds', 'runId', 'historical', 'difference'],
  emits: ['nodeSelected', 'nodeDoubleClicked'],
  setup(props, { emit, expose }) { expose(topologyCalls); return () => h('div', { class: 'topology-probe' },
    (props.blueprint?.nodes || []).map((node: { nodeId: string }) => h('button', {
      'data-node': node.nodeId, onClick: () => emit('nodeSelected', node.nodeId),
      onDblclick: () => emit('nodeDoubleClicked', node.nodeId),
    }, node.nodeId))) },
})
const cleanups: Array<() => void> = []
const settle = async () => { await flushPromises(); await nextTick(); await flushPromises() }
const setup = async () => {
  const runId = ref<string | null>('run')
  const live = ref<GraphProjection | null>(graph(2))
  const watermark = ref(1)
  const observed = ref(observation())
  const runtime = ref({ runId: 'run', nodes: { read: { phase: 'completed' }, review: { phase: 'running' } } } as unknown as RuntimeEventStore)
  const api = { getGraphVersions: vi.fn(async (id: string) => history(id)),
    getGraphSnapshot: vi.fn(async (_id: string, blueprintId: string | null) => graph(blueprintId?.endsWith('1') ? 1 : 2)) }
  const scope = effectScope()
  const versions = scope.run(() => createGraphVersions(runId, live, watermark, api))!
  const Harness = defineComponent({ setup() {
    provide(graphVersionsKey, versions)
    return () => h('div', [h(WorkspaceExplorer, { projection: projection(), activeEditorId: 'graph', selectedRunId: runId.value }),
      h(GraphEditor, { graph: live.value, graphNodes, selectedSemanticTaskKey: null, focusNodeId: null,
        runId: runId.value, runtimeObservation: observed.value, runtimeStore: runtime.value })])
  } })
  const wrapper = mount(Harness, { global: { stubs: { AcgTopologyGraph: topologyStub, 'el-icon': true } } })
  cleanups.push(() => { wrapper.unmount(); scope.stop() })
  await settle()
  return { wrapper, versions, api, runId, live, observed, runtime,
    editor: () => wrapper.findComponent(GraphEditor),
    topology: () => wrapper.findComponent(topologyStub),
    explorer: () => wrapper.findComponent(WorkspaceExplorer),
  }
}

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); vi.spyOn(agentosApi, 'listWorkspaceFiles').mockRejectedValue(new Error('no workspace')) })
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); vi.restoreAllMocks(); localStorage.clear() })

describe('graph version browsing across Explorer and editor', () => {
  it('keeps historical snapshots separate from live runtime state and current semantic task navigation', async () => {
    const state = await setup()
    expect(state.topology().props('runtimePhases')).toEqual({ read: 'completed', review: 'running' })
    expect(state.topology().props('completedStepIds')).toEqual(['read'])
    await state.wrapper.find('select[aria-label="选择图版本"]').setValue('graph-bp1')
    await settle()
    expect(state.topology().props()).toMatchObject({ runId: null, historical: true,
      runtimePhases: {}, stepStates: [], completedStepIds: [] })
    expect(state.topology().props('blueprint').graphVersion).toBe(1)
    const selections = state.editor().emitted('selectSemanticTask')?.length || 0
    await state.wrapper.find('[data-node="read"]').trigger('click')
    await state.wrapper.find('[data-node="read"]').trigger('dblclick')
    expect(state.editor().emitted('selectSemanticTask')?.length || 0).toBe(selections)
    expect(state.editor().emitted('openSemanticTask')).toBeUndefined()
    state.observed.value = observation()
    state.runtime.value = { runId: 'run', nodes: { read: { phase: 'failed' } } } as unknown as RuntimeEventStore
    await settle()
    expect(state.topology().props()).toMatchObject({ runId: null, runtimePhases: {}, stepStates: [], completedStepIds: [] })
  })

  it('nests collapsible versions under graph.acg and shares selection with the toolbar', async () => {
    const state = await setup()
    const explorer = state.explorer()
    expect(explorer.findAll('.workspace-tree__section')).toHaveLength(4)
    expect(explorer.findAll('.workspace-tree__section-toggle').map(item => item.text()).join(' ')).not.toContain('图版本')
    const nested = explorer.find('.workspace-tree__graph-versions')
    expect(nested.element.previousElementSibling?.textContent).toContain('graph.acg')
    await nested.findAll('.version-row')[1].trigger('click')
    await settle()
    expect(state.wrapper.find<HTMLSelectElement>('select').element.value).toBe('graph-bp1')
    expect(state.versions.selectedKey.value).toBe('graph-bp1')
    expect(explorer.emitted('open')?.at(-1)?.[0].kind).toBe('graph')
    await state.wrapper.find('select').setValue('graph-bp2')
    await settle()
    expect(explorer.findAll('.version-row')[0].attributes('aria-pressed')).toBe('true')
    await explorer.find('[aria-label="展开或收起图版本"]').trigger('click')
    expect(explorer.find('.workspace-tree__graph-versions').exists()).toBe(false)
    expect(state.versions.selectedKey.value).toBe('graph-bp2')
    await explorer.find('[aria-label="展开或收起图版本"]').trigger('click')
    expect(explorer.findAll('.version-row')).toHaveLength(2)
    await explorer.find('.version-follow').trigger('click')
    expect(state.versions.following.value).toBe(true)
  })

  it('shows removed nodes as comparison evidence without navigating to a current semantic task', async () => {
    const state = await setup()
    await state.wrapper.find('.version-toolbar__compare').trigger('click')
    await settle()
    expect(state.topology().props('difference').removedNodeIds).toEqual(['removed'])
    expect(state.topology().props('blueprint').nodes.map((node: { nodeId: string }) => node.nodeId)).toEqual(['read', 'review', 'removed'])
    const before = state.editor().emitted('selectSemanticTask')?.length || 0
    await state.wrapper.find('[data-node="removed"]').trigger('click')
    await state.wrapper.find('[data-node="removed"]').trigger('dblclick')
    expect(state.editor().emitted('selectSemanticTask')?.length || 0).toBe(before)
    expect(state.editor().emitted('openSemanticTask')).toBeUndefined()
    await state.wrapper.find('.graph-difference__nodes .is-removed').trigger('click')
    await state.wrapper.find('.graph-difference__nodes .is-removed').trigger('click')
    expect(topologyCalls.focusNode.mock.calls).toEqual([['removed'], ['removed']])
    await state.wrapper.find('[data-node="review"]').trigger('dblclick')
    expect(state.editor().emitted('openSemanticTask')).toEqual([['task:review']])
    expect(state.live.value?.nodes.some(node => node.nodeId === 'removed')).toBe(false)
  })

  it('does not attach another run runtime phases while observations catch up after run selection', async () => {
    const state = await setup()
    state.runId.value = 'new-run'
    await settle()
    expect(state.topology().props('stepStates')).toEqual([])
    expect(state.topology().props('completedStepIds')).toEqual([])
    expect(state.topology().props('runtimePhases')).toEqual({})
  })

  it('ignores a delayed historical snapshot after the user returns to the current graph', async () => {
    const state = await setup()
    let resolveOld!: (snapshot: GraphProjection) => void
    state.api.getGraphSnapshot.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    await state.wrapper.find('select').setValue('graph-bp1')
    await settle()
    expect(state.topology().exists()).toBe(false)
    expect(state.editor().get('.graph-editor__empty').text()).toContain('正在加载图快照')
    await state.wrapper.find('.version-toolbar__follow').trigger('click')
    await settle()
    resolveOld(graph(1))
    await settle()
    expect(state.topology().props('blueprint').graphVersion).toBe(2)
    expect(state.topology().props('historical')).toBe(false)
    expect(state.topology().props('runId')).toBe('run')
    expect(state.topology().props('runtimePhases')).toEqual({ read: 'completed', review: 'running' })
  })

  it('does not borrow a different graph with the same version while the new run graph is loading', async () => {
    const state = await setup()
    state.api.getGraphVersions.mockResolvedValue(history('new-run', 'new-graph'))
    state.api.getGraphSnapshot.mockReturnValue(new Promise(() => {}))
    state.runId.value = 'new-run'
    await settle()
    expect(state.versions.displayGraph.value).toBeNull()
    expect(state.topology().exists()).toBe(false)
    expect(state.editor().get('.graph-editor__empty').text()).toContain('正在加载图快照')
  })
})
