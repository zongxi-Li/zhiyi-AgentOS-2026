import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi, type MissionWorkspaceProjection, type WorkspaceEntry } from '@/services/api/agentos'
import MissionWorkspaceView from './MissionWorkspaceView.vue'

const workspaceLayoutStub = {
  template: '<div class="workspace-layout-stub"><aside><slot name="left" /></aside><main><slot name="main" /></main><aside><slot name="right" /></aside></div>'
}

const graphEditorStub = {
  emits: ['selectSemanticTask', 'openSemanticTask'],
  template: '<div class="graph-editor-stub"><button class="graph-select" @click="$emit(\'selectSemanticTask\', \'capacity\')">select</button><button class="graph-open" @click="$emit(\'openSemanticTask\', \'capacity\')">open</button></div>'
}

const artifactEditorStub = {
  props: ['entry', 'available'],
  emits: ['locateGraph'],
  template: '<div class="artifact-editor-stub"><span>{{ entry.name }}</span><span>{{ available ? "available" : "Not available in this Run" }}</span><button class="artifact-locate" :disabled="!available || entry.identityQuality === \'legacy\'" @click="$emit(\'locateGraph\')">locate</button></div>'
}

const missionEditorStub = { template: '<div class="mission-editor-stub">mission.md</div>' }

const folders = (): WorkspaceEntry[] => [
  { entryId: 'folder:overview', kind: 'folder', name: 'Overview', group: 'overview', displayOrder: 0 },
  { entryId: 'folder:steps', kind: 'folder', name: 'Steps', group: 'steps', displayOrder: 0 },
  { entryId: 'folder:output', kind: 'folder', name: 'Output', group: 'output', displayOrder: 0 },
  { entryId: 'folder:runs', kind: 'folder', name: 'Runs', group: 'runs', displayOrder: 0 }
]

const runEntries = (): WorkspaceEntry[] => [
  { entryId: 'run:run_1', kind: 'run', name: 'run_1', group: 'runs', displayOrder: 0, runId: 'run_1', status: 'succeeded' },
  { entryId: 'run:run_2', kind: 'run', name: 'run_2', group: 'runs', displayOrder: 1, runId: 'run_2', status: 'running', isActive: true }
]

const artifact = (key = 'primary', id = 'artifact_1', legacy = false): WorkspaceEntry => ({
  entryId: `task:capacity:${key}`, kind: 'artifact', name: `${key}.md`, group: 'steps', displayOrder: 0,
  semanticTaskKey: legacy ? null : 'capacity', artifactKey: key, artifactId: legacy ? null : id,
  contentRef: `manifest_${id}`, mediaType: 'text/markdown', identityQuality: legacy ? 'legacy' : 'canonical', runId: 'run_2'
})

const projection = (overrides: Partial<MissionWorkspaceProjection> = {}): MissionWorkspaceProjection => ({
  mission: { missionId: 'mission_1', userId: 'user_1', goal: '设备人员规划', description: '目标', metadata: { domain: 'ops' }, createdAt: '2026-08-28T00:00:00Z', updatedAt: '2026-08-28T00:00:00Z', status: 'created' },
  activeRun: { runId: 'run_2', status: 'running', createdAt: '2026-08-28T00:02:00Z', isActive: true },
  runs: [
    { runId: 'run_1', status: 'succeeded', createdAt: '2026-08-28T00:01:00Z', isActive: false },
    { runId: 'run_2', status: 'running', createdAt: '2026-08-28T00:02:00Z', isActive: true }
  ],
  activeGraph: { graphId: 'graph_2', nodes: [{ nodeId: 'node_capacity', nodeType: 'step', name: 'Capacity' }], edges: [] },
  graphNodes: [{ acgNodeId: 'node_capacity', nodeType: 'step', name: 'Capacity', semanticTaskKey: 'capacity', taskId: 'task_capacity', identityQuality: 'canonical', displayOrder: 0 }],
  diagnostics: [],
  entries: [
    ...folders(),
    { entryId: 'overview:graph.acg', kind: 'graph', name: 'graph.acg', group: 'overview', displayOrder: 0 },
    { entryId: 'overview:mission.md', kind: 'virtual_document', name: 'mission.md', group: 'overview', displayOrder: 1, content: '# Mission' },
    artifact(),
    ...runEntries()
  ],
  ...overrides
})

const mountWorkspace = async (resolved: MissionWorkspaceProjection | ((runId?: string) => MissionWorkspaceProjection) = projection()) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agentos/missions/:missionId/workspace', component: MissionWorkspaceView }]
  })
  await router.push('/agentos/missions/mission_1/workspace')
  await router.isReady()
  const getWorkspace = vi.isMockFunction(agentosApi.getMissionWorkspace)
    ? vi.mocked(agentosApi.getMissionWorkspace)
    : vi.spyOn(agentosApi, 'getMissionWorkspace')
  if (!getWorkspace.getMockImplementation()) {
    getWorkspace.mockImplementation(async (_missionId, options) => {
      return typeof resolved === 'function' ? resolved(options.runId) : resolved
    })
  }
  const wrapper = mount(MissionWorkspaceView, {
    global: {
      plugins: [router],
      stubs: {
        WorkbenchLayout: workspaceLayoutStub,
        GraphEditor: graphEditorStub,
        ArtifactEditor: artifactEditorStub,
        MissionEditor: missionEditorStub,
        'el-icon': true
      }
    }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('MissionWorkspaceView', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads one Mission Workspace projection and renders the project shell', async () => {
    const { wrapper } = await mountWorkspace()
    expect(agentosApi.getMissionWorkspace).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Mission Project')
    expect(wrapper.text()).toContain('OVERVIEW')
    expect(wrapper.text()).toContain('MISSION WORKSPACE')
  })

  it('opens graph.acg as the default editor and keeps graph separate from results', async () => {
    const { wrapper } = await mountWorkspace()
    expect(wrapper.find('.editor-tab').text()).toContain('graph.acg')
    expect(wrapper.find('.graph-editor-stub').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('最终答案')
  })

  it('opens mission.md and artifacts as separate tabs without duplicate identities', async () => {
    const { wrapper } = await mountWorkspace()
    const entries = wrapper.findAll('.workspace-tree__entry')
    await entries.find(item => item.text().includes('mission.md'))?.trigger('click')
    await entries.find(item => item.text().includes('primary.md'))?.trigger('click')
    await entries.find(item => item.text().includes('primary.md'))?.trigger('click')
    expect(wrapper.findAll('.editor-tab')).toHaveLength(3)
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('primary.md')
  })

  it('closes the active editor and activates the neighboring tab', async () => {
    const { wrapper } = await mountWorkspace()
    const mission = wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('mission.md'))
    await mission?.trigger('click')
    await wrapper.find('.editor-tab.is-active .editor-tab__close').trigger('click')
    expect(wrapper.findAll('.editor-tab')).toHaveLength(1)
    expect(wrapper.find('.editor-tab').text()).toContain('graph.acg')
  })

  it('maps a graph double click to one matching artifact', async () => {
    const { wrapper } = await mountWorkspace()
    await wrapper.find('.graph-open').trigger('click')
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('primary.md')
  })

  it('offers a lightweight choice when one semantic task has multiple artifacts', async () => {
    const multi = projection({ entries: [...projection().entries, artifact('assumptions', 'artifact_2')] })
    const { wrapper } = await mountWorkspace(multi)
    await wrapper.find('.graph-open').trigger('click')
    expect(wrapper.find('.artifact-choice').exists()).toBe(true)
    expect(wrapper.findAll('.artifact-choice__item')).toHaveLength(2)
    await wrapper.findAll('.artifact-choice__item')[1].trigger('click')
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('assumptions.md')
  })

  it('selects a graph node even when no artifact is available', async () => {
    const noArtifact = projection({ entries: projection().entries.filter(item => item.kind !== 'artifact') })
    const { wrapper } = await mountWorkspace(noArtifact)
    await wrapper.find('.graph-open').trigger('click')
    expect(wrapper.find('.artifact-choice').exists()).toBe(false)
    expect(wrapper.find('.graph-editor-stub').exists()).toBe(true)
  })

  it('locates a canonical artifact in graph and keeps the artifact tab open', async () => {
    const { wrapper } = await mountWorkspace()
    const artifactRow = wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('primary.md'))
    await artifactRow?.trigger('click')
    await wrapper.find('.artifact-locate').trigger('click')
    expect(wrapper.find('.graph-editor-stub').exists()).toBe(true)
    expect(wrapper.findAll('.editor-tab')).toHaveLength(2)
  })

  it('disables graph positioning for legacy artifacts', async () => {
    const legacy = projection({ entries: [...folders(), ...runEntries(), artifact('legacy', 'legacy', true), { entryId: 'overview:graph.acg', kind: 'graph', name: 'graph.acg', group: 'overview', displayOrder: 0 }, { entryId: 'overview:mission.md', kind: 'virtual_document', name: 'mission.md', group: 'overview', displayOrder: 1, content: '# Mission' }] })
    const { wrapper } = await mountWorkspace(legacy)
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('legacy.md'))?.trigger('click')
    expect(wrapper.find('.artifact-locate').attributes('disabled')).toBeDefined()
  })

  it('switches from current to historical Run through a new workspace request', async () => {
    const historical = projection({ activeRun: { runId: 'run_1', status: 'succeeded', createdAt: '2026-08-28T00:01:00Z', isActive: true }, entries: projection().entries.filter(item => item.entryId !== 'task:capacity:primary') })
    const getWorkspace = vi.spyOn(agentosApi, 'getMissionWorkspace').mockImplementation(async (_id, options) => options.runId === 'run_1' ? historical : projection())
    const { wrapper } = await mountWorkspace()
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('run_1'))?.trigger('click')
    await flushPromises()
    expect(getWorkspace).toHaveBeenLastCalledWith('mission_1', expect.objectContaining({ runId: 'run_1' }))
    expect(wrapper.text()).toContain('Historical / Read-only')
  })

  it('switches historical back to the current Run explicitly', async () => {
    const historical = projection({ activeRun: { runId: 'run_1', status: 'succeeded', createdAt: '2026-08-28T00:01:00Z', isActive: true }, entries: projection().entries.filter(item => item.entryId !== 'task:capacity:primary') })
    const { wrapper } = await mountWorkspace(runId => runId === 'run_1' ? historical : projection())
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('run_1'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('run_2'))?.trigger('click')
    await flushPromises()
    expect(agentosApi.getMissionWorkspace).toHaveBeenLastCalledWith('mission_1', expect.objectContaining({ runId: 'run_2' }))
    expect(wrapper.text()).not.toContain('Historical / Read-only')
  })

  it('keeps the stable artifact tab identity and shows missing content in a historical Run', async () => {
    const historical = projection({ activeRun: { runId: 'run_1', status: 'succeeded', createdAt: '2026-08-28T00:01:00Z', isActive: true }, entries: projection().entries.filter(item => item.entryId !== 'task:capacity:primary') })
    const { wrapper } = await mountWorkspace((_runId) => _runId === 'run_1' ? historical : projection())
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('primary.md'))?.trigger('click')
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('run_1'))?.trigger('click')
    await flushPromises()
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('Not available in this Run')
    expect(wrapper.findAll('.editor-tab')).toHaveLength(2)
  })

  it('shows NO_ACTIVE_RUN diagnostics and falls back to mission.md', async () => {
    const empty = projection({ activeRun: null, entries: [...folders(), { entryId: 'overview:mission.md', kind: 'virtual_document', name: 'mission.md', group: 'overview', displayOrder: 1, content: '# Empty' }, ...runEntries()], diagnostics: [{ code: 'NO_ACTIVE_RUN', message: '没有 Run', severity: 'info' }] })
    const { wrapper } = await mountWorkspace(empty)
    expect(wrapper.text()).toContain('NO_ACTIVE_RUN')
    expect(wrapper.text()).toContain('mission.md')
  })

  it('surfaces API failure with a visible retry state', async () => {
    vi.spyOn(agentosApi, 'getMissionWorkspace').mockRejectedValue(new Error('offline'))
    const { wrapper } = await mountWorkspace()
    expect(wrapper.text()).toContain('Mission Workspace unavailable')
    expect(wrapper.text()).toContain('重新加载')
  })

  it('does not request Artifact content while the default graph editor is open', async () => {
    const getContent = vi.spyOn(agentosApi, 'getArtifactContent').mockResolvedValue({ manifestId: 'manifest_1', mediaType: 'text/markdown', content: 'body' })
    const { wrapper } = await mountWorkspace()
    expect(getContent).not.toHaveBeenCalled()
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('primary.md'))?.trigger('click')
    await flushPromises()
    expect(getContent).not.toHaveBeenCalled()
  })
})
