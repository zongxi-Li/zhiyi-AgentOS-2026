import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi, type MissionWorkspaceProjection, type WorkspaceEntry } from '@/services/api/agentos'
import MissionWorkspaceView from './MissionWorkspaceView.vue'

const defaultLayoutStubState = {
  leftAutoHidden: false,
  restoreLeftPane: () => undefined
}
let layoutStubState = { ...defaultLayoutStubState }

const workspaceLayoutStub = {
  setup: () => ({ noop: () => undefined, state: layoutStubState }),
  template: '<div class="workspace-layout-stub"><aside><slot name="left" /></aside><main><slot name="main" :left-auto-hidden="state.leftAutoHidden" :restore-left-pane="state.restoreLeftPane" :right-auto-hidden="false" :right-enabled="true" :right-pane-visible="true" :right-collapsed-by-user="false" :toggle-right-pane="noop" /></main><aside><slot name="right" /></aside><section><slot name="bottom" :collapsed="false" :set-collapsed="noop" :toggle-collapsed="noop" /></section></div>'
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

const progressEditorStub = {
  props: ['entry', 'runId'],
  template: '<div class="progress-editor-stub">运行进度 {{ runId }}</div>'
}

const taskEntry = (): WorkspaceEntry => ({
  entryId: 'task:capacity', kind: 'task', name: 'Capacity', group: 'steps', displayOrder: 0,
  semanticTaskKey: 'capacity', taskId: 'task_capacity', objective: 'Form a capacity plan',
  status: 'completed', attemptCount: 1, latestAttemptId: 'attempt_capacity', artifactCount: 1,
  acgNodeId: 'node_capacity', identityQuality: 'canonical'
})

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
  entryId: `task:capacity:${key}`, kind: 'artifact', name: `${key}.md`, group: 'steps', displayOrder: 0, parentEntryId: 'task:capacity',
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
    taskEntry(),
    artifact(),
    ...runEntries()
  ],
  ...overrides
})

const mountWorkspace = async (
  resolved: MissionWorkspaceProjection | ((runId?: string) => MissionWorkspaceProjection) = projection(),
  url = '/agentos/missions/mission_1/workspace'
) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agentos/missions/:missionId/workspace', component: MissionWorkspaceView }]
  })
  await router.push(url)
  await router.isReady()
  const getWorkspace = vi.isMockFunction(agentosApi.getMissionWorkspace)
    ? vi.mocked(agentosApi.getMissionWorkspace)
    : vi.spyOn(agentosApi, 'getMissionWorkspace')
  if (!getWorkspace.getMockImplementation()) {
    getWorkspace.mockImplementation(async (_missionId, options) => {
      return typeof resolved === 'function' ? resolved(options.runId) : resolved
    })
  }
  const getRun = vi.isMockFunction(agentosApi.getWorkflowRun)
    ? vi.mocked(agentosApi.getWorkflowRun)
    : vi.spyOn(agentosApi, 'getWorkflowRun')
  if (!getRun.getMockImplementation()) {
    getRun.mockImplementation(async runId => ({
      runId,
      missionId: 'mission_1',
      workflowId: 'workflow_1',
      domain: 'ops',
      status: (typeof resolved === 'function' ? resolved(runId)?.activeRun?.status : resolved.activeRun?.status) || 'succeeded',
      steps: []
    } as any))
  }
  vi.spyOn(agentosApi, 'getWorkflowTrace').mockResolvedValue({
    runId: 'run_2', missionId: 'mission_1', workflowId: 'workflow_1', domain: 'ops', status: 'succeeded', eventCount: 0, events: []
  } as any)
  vi.spyOn(agentosApi, 'getRunProvenance').mockResolvedValue({ runId: 'run_2', events: [], productions: [], consumptions: [], interactions: [] })
  vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })
  vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({ nodes: [] } as any)
  const wrapper = mount(MissionWorkspaceView, {
    global: {
      plugins: [router],
      stubs: {
        WorkbenchLayout: workspaceLayoutStub,
        GraphEditor: graphEditorStub,
        ArtifactEditor: artifactEditorStub,
        MissionEditor: missionEditorStub,
        ProgressEditor: progressEditorStub,
        'el-icon': true
      }
    }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('MissionWorkspaceView', () => {
  afterEach(() => {
    layoutStubState = { ...defaultLayoutStubState }
    vi.restoreAllMocks()
  })

  it('loads one Mission Workspace projection and renders the project shell', async () => {
    const { wrapper } = await mountWorkspace()
    expect(agentosApi.getMissionWorkspace).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('PROJECT')
    expect(wrapper.text()).toContain('OVERVIEW')
    expect(wrapper.find('.editor-inspector-trigger').attributes('aria-label')).toBe('收起 Inspector')
    expect(wrapper.find('.editor-navigator-trigger').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('MISSION WORKSPACE')
  })

  it('offers a click trigger to bring back the auto-hidden left navigator', async () => {
    const restoreLeftPane = vi.fn()
    layoutStubState.leftAutoHidden = true
    layoutStubState.restoreLeftPane = restoreLeftPane
    const { wrapper } = await mountWorkspace()

    expect(wrapper.find('.editor-navigator-trigger').attributes('aria-label')).toBe('唤醒项目导航')
    await wrapper.find('.editor-navigator-trigger').trigger('click')
    expect(restoreLeftPane).toHaveBeenCalledTimes(1)
  })

  it('opens the live progress tab for an active Run with graph.acg one click away', async () => {
    const { wrapper } = await mountWorkspace()
    const tabs = wrapper.findAll('.editor-tab')
    expect(tabs[0].text()).toContain('运行进度')
    expect(tabs.map(tab => tab.text()).some(text => text.includes('graph.acg'))).toBe(true)
    expect(wrapper.find('.progress-editor-stub').exists()).toBe(true)
    expect(wrapper.find('.editor-group__toolbar').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('最终答案')
  })

  it('opens mission.md and artifacts as separate tabs without duplicate identities', async () => {
    const { wrapper } = await mountWorkspace()
    const entries = wrapper.findAll('.workspace-tree__entry')
    await entries.find(item => item.text().includes('mission.md'))?.trigger('click')
    await entries.find(item => item.text().includes('primary.md'))?.trigger('click')
    await entries.find(item => item.text().includes('primary.md'))?.trigger('click')
    expect(wrapper.findAll('.editor-tab')).toHaveLength(4)
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('primary.md')
  })

  it('closes the active editor and activates the neighboring tab', async () => {
    const { wrapper } = await mountWorkspace()
    const mission = wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('mission.md'))
    await mission?.trigger('click')
    await wrapper.find('.editor-tab.is-active .editor-tab__close').trigger('click')
    expect(wrapper.findAll('.editor-tab')).toHaveLength(2)
    expect(wrapper.findAll('.editor-tab').at(-1)?.text()).toContain('graph.acg')
  })

  const activateGraphTab = async (wrapper: VueWrapper) => {
    const tab = wrapper.findAll('.editor-tab').find(tab => tab.text().includes('graph.acg'))
    await tab?.find('.editor-tab__main').trigger('click')
  }

  it('maps a graph double click to the matching TaskEditor', async () => {
    const { wrapper } = await mountWorkspace()
    await activateGraphTab(wrapper)
    await wrapper.find('.graph-open').trigger('click')
    expect(wrapper.find('.task-editor').exists()).toBe(true)
    expect(wrapper.find('.task-editor').text()).toContain('capacity')
  })

  it('keeps multiple Artifacts inside the matching TaskEditor', async () => {
    const multi = projection({ entries: [...projection().entries, artifact('assumptions', 'artifact_2')] })
    const { wrapper } = await mountWorkspace(multi)
    await activateGraphTab(wrapper)
    await wrapper.find('.graph-open').trigger('click')
    expect(wrapper.find('.artifact-choice').exists()).toBe(false)
    expect(wrapper.findAll('.task-editor__artifacts button')).toHaveLength(2)
    await wrapper.findAll('.task-editor__artifacts button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('assumptions.md')
  })

  it('selects a graph node even when no artifact is available', async () => {
    const noArtifact = projection({ entries: projection().entries.filter(item => item.kind !== 'artifact') })
    const { wrapper } = await mountWorkspace(noArtifact)
    await activateGraphTab(wrapper)
    await wrapper.find('.graph-open').trigger('click')
    expect(wrapper.find('.artifact-choice').exists()).toBe(false)
    expect(wrapper.find('.task-editor').exists()).toBe(true)
  })

  it('locates a canonical artifact in graph and keeps the artifact tab open', async () => {
    const { wrapper } = await mountWorkspace()
    const artifactRow = wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('primary.md'))
    await artifactRow?.trigger('click')
    await wrapper.find('.artifact-locate').trigger('click')
    expect(wrapper.find('.graph-editor-stub').exists()).toBe(true)
    expect(wrapper.findAll('.editor-tab')).toHaveLength(3)
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

  it('creates a successor from the selected terminal Run and switches to it', async () => {
    const source = projection({
      activeRun: { runId: 'run_1', status: 'succeeded', createdAt: '2026-08-28T00:01:00Z', isActive: true }
    })
    const successor = projection({
      activeRun: { runId: 'run_3', status: 'running', createdAt: '2026-08-28T00:03:00Z', isActive: true },
      runs: [...source.runs, { runId: 'run_3', status: 'running', createdAt: '2026-08-28T00:03:00Z', isActive: true }]
    })
    vi.spyOn(agentosApi, 'getWorkflowHistoryConfig').mockResolvedValue({
      runId: 'run_1', reviewMode: 'auto', enabledPluginIds: ['plugin_1'], input: { taskGoal: '设备规划' }
    })
    const rerun = vi.spyOn(agentosApi, 'rerunWorkflowAsync').mockResolvedValue({
      runId: 'run_3', missionId: 'mission_1', workflowId: 'workflow_1', domain: 'ops', status: 'pending', steps: []
    } as any)
    const { wrapper, router } = await mountWorkspace(runId => runId === 'run_3' ? successor : source, '/agentos/missions/mission_1/workspace?runId=run_1')

    await wrapper.find('.workspace-tree__rerun').trigger('click')
    await flushPromises()

    expect(rerun).toHaveBeenCalledWith('mission_1', expect.objectContaining({
      sourceRunId: 'run_1', rerunReason: 'manual_rerun', input: { taskGoal: '设备规划' }, clientRequestId: expect.any(String)
    }))
    expect(router.currentRoute.value.query.runId).toBe('run_3')
    expect(agentosApi.getMissionWorkspace).toHaveBeenLastCalledWith('mission_1', expect.objectContaining({ runId: 'run_3' }))
  })

  it('keeps the stable artifact tab identity and shows missing content in a historical Run', async () => {
    const historical = projection({ activeRun: { runId: 'run_1', status: 'succeeded', createdAt: '2026-08-28T00:01:00Z', isActive: true }, entries: projection().entries.filter(item => item.entryId !== 'task:capacity:primary') })
    const { wrapper } = await mountWorkspace((_runId) => _runId === 'run_1' ? historical : projection())
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('primary.md'))?.trigger('click')
    await wrapper.findAll('.workspace-tree__entry').find(item => item.text().includes('run_1'))?.trigger('click')
    await flushPromises()
    expect(wrapper.find('.artifact-editor-stub').text()).toContain('Not available in this Run')
    expect(wrapper.findAll('.editor-tab')).toHaveLength(3)
  })

  it('shows NO_ACTIVE_RUN diagnostics and falls back to mission.md', async () => {
    const empty = projection({ activeRun: null, entries: [...folders(), { entryId: 'overview:mission.md', kind: 'virtual_document', name: 'mission.md', group: 'overview', displayOrder: 1, content: '# Empty' }, ...runEntries()], diagnostics: [{ code: 'NO_ACTIVE_RUN', message: '没有 Run', severity: 'info' }] })
    const { wrapper } = await mountWorkspace(empty)
    expect(wrapper.find('.workbench-bottom-panel__tab').text()).toContain('Problems')
    expect(wrapper.find('.workbench-bottom-panel__tab small').text()).toBe('1')
    expect(wrapper.find('.problems-panel').text()).toContain('NO_ACTIVE_RUN')
    expect(wrapper.text()).toContain('mission.md')
  })

  it('exposes the fixed runtime observation panels through the Workbench registry', async () => {
    const { wrapper } = await mountWorkspace()
    expect(wrapper.findAll('.workbench-bottom-panel__tab').map(tab => tab.text())).toEqual([
      'Problems0', 'Communication0', 'Trace0', 'Events0', 'Tool Calls0'
    ])
  })

  it('surfaces API failure with a visible retry state', async () => {
    vi.spyOn(agentosApi, 'getMissionWorkspace').mockRejectedValue(new Error('offline'))
    const { wrapper } = await mountWorkspace()
    expect(wrapper.text()).toContain('Mission Workspace unavailable')
    expect(wrapper.text()).toContain('重新加载')
  })

  it('waits for a deferred Run identity projection after the Runtime Run is accepted', async () => {
    vi.useFakeTimers()
    try {
      const getWorkspace = vi.spyOn(agentosApi, 'getMissionWorkspace')
        .mockRejectedValueOnce({ response: { status: 404 } })
        .mockResolvedValue(projection())
      const getRun = vi.spyOn(agentosApi, 'getWorkflowRun').mockResolvedValue({
        runId: 'run_2', missionId: 'mission_1', workflowId: 'workflow_1', domain: 'ops',
        status: 'running', steps: []
      } as any)

      const { wrapper } = await mountWorkspace(projection(), '/agentos/missions/mission_1/workspace?runId=run_2')
      await flushPromises()

      expect(getRun).toHaveBeenCalledWith('run_2', expect.objectContaining({ signal: expect.any(AbortSignal) }))
      expect(getWorkspace).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()

      expect(getWorkspace).toHaveBeenCalledTimes(2)
      expect(wrapper.text()).toContain('PROJECT')
    } finally {
      vi.useRealTimers()
    }
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
