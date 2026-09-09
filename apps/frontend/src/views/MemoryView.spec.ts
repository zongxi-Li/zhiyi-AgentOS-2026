import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import type { MissionListItem, RunMemoryEvent, WorkflowRunSummary } from '@/services/api/agentos'
import MemoryView from './MemoryView.vue'

const layoutStub = {
  template: '<main class="layout-stub"><slot name="main" /></main>'
}

function makeRun(overrides: Partial<WorkflowRunSummary> & { runId: string }): WorkflowRunSummary {
  return {
    missionId: `mission_${overrides.runId}`,
    workflowId: 'native_acg_runtime_v1',
    status: 'completed',
    phase: 'completed',
    message: '',
    percent: 100,
    totalSteps: 3,
    pendingSteps: 0,
    runningSteps: 0,
    waitingReviewSteps: 0,
    retryingSteps: 0,
    failedSteps: 0,
    cancelledSteps: 0,
    currentStepId: null,
    activeStepIds: [],
    startedAt: '2026-09-08T12:00:00Z',
    updatedAt: '2026-09-08T12:30:00Z',
    progress: 100,
    percentage: 100,
    title: '极端天气应急补货',
    ...overrides
  }
}

const memoryEvents: RunMemoryEvent[] = [
  {
    kind: 'memory_access',
    stepId: 'native_general_agent',
    retrievalMode: 'bm25_vector_rrf',
    hitRefs: [],
    budget: null,
    fallbackReason: null,
    createdAt: '2026-09-08T12:10:00Z'
  },
  {
    kind: 'memory_event',
    eventId: 'memoryevent_1',
    runId: 'run_1',
    stepId: 'native_general_agent',
    commitId: 'commit:run_1:native_general_agent:0',
    summary: 'Workset completed from 1 persisted fragment result(s).',
    metrics: { fieldCount: 5, modelInvocationCount: 1 },
    createdAt: '2026-09-08T12:11:00Z'
  },
  {
    kind: 'memory_access',
    stepId: 'native_general_agent_2',
    retrievalMode: 'bm25_vector_rrf',
    hitRefs: ['memory:run_1:native_general_agent'],
    budget: null,
    fallbackReason: null,
    createdAt: '2026-09-08T12:12:00Z'
  },
  {
    kind: 'memory_event',
    eventId: 'memoryevent_2',
    runId: 'run_1',
    stepId: 'native_general_agent_2',
    commitId: 'commit:run_1:native_general_agent_2:0',
    summary: '提取了用户规模与文档量事实。',
    metrics: { fieldCount: 2, modelInvocationCount: 1 },
    createdAt: '2026-09-08T12:13:00Z'
  },
  {
    kind: 'phase_capsule',
    phaseId: 'deliver',
    capsuleRef: 'capsule:run_1:deliver',
    sourceMemoryRefs: ['memory:run_1:native_general_agent_2'],
    tokenCount: 384
  }
]

const mountedWrappers: Array<{ unmount: () => void }> = []

const mountPage = async (options: {
  runs?: WorkflowRunSummary[]
  missions?: MissionListItem[]
  events?: RunMemoryEvent[]
  query?: Record<string, string>
} = {}) => {
  const runs = options.runs ?? [makeRun({ runId: 'run_1' }), makeRun({ runId: 'run_2', title: '知识服务平台', status: 'failed' })]
  const missions = options.missions ?? runs.map((run, index) => ({
    missionId: run.missionId,
    userId: 'user_1',
    title: run.title || `Mission ${index + 1}`,
    description: '',
    status: 'active',
    latestRunId: run.runId,
    latestRunStatus: run.status,
    createdAt: run.createdAt || run.startedAt || '',
    updatedAt: run.updatedAt || run.startedAt || '',
    runCount: 1
  }))
  const events = options.events ?? memoryEvents
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/agentos/memory', name: 'MemoryCenter', component: MemoryView }
    ]
  })
  await router.push({ path: '/agentos/memory', query: options.query ?? {} })
  await router.isReady()
  const listRunsSpy = vi.spyOn(agentosApi, 'listWorkflowRuns').mockResolvedValue({ items: runs, total: runs.length, page: 1, pageSize: 50 })
  const listMissionsSpy = vi.spyOn(agentosApi, 'listMissions').mockResolvedValue({ items: missions, total: missions.length, page: 1, pageSize: 100 })
  const listEventsSpy = vi.spyOn(agentosApi, 'listMemoryEvents').mockResolvedValue({
    runId: 'run_1',
    items: events,
    total: events.length
  })
  const wrapper = mount(MemoryView, {
    global: { plugins: [router], stubs: { WorkbenchLayout: layoutStub, Teleport: true } }
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return { wrapper, listRunsSpy, listMissionsSpy, listEventsSpy }
}

afterEach(() => {
  while (mountedWrappers.length) {
    mountedWrappers.pop()?.unmount()
  }
  vi.restoreAllMocks()
})

describe('MemoryView', () => {
  it('加载运行列表并自动选中首个运行渲染记忆统计', async () => {
    const { wrapper, listEventsSpy } = await mountPage()
    expect(listEventsSpy.mock.calls[0]?.[0]).toBe('run_1')
    const stats = wrapper.findAll('.memory-stat')
    expect(stats.map(stat => stat.find('strong').text())).toEqual(['2', '2', '1', '1'])
    expect(wrapper.find('.memory-capsule__phase').text()).toBe('deliver')
  })

  it('渲染步骤卡与召回命中 chip', async () => {
    const { wrapper } = await mountPage()
    const steps = wrapper.findAll('.memory-step')
    expect(steps).toHaveLength(2)
    expect(steps[1].find('.memory-step__id').text()).toBe('native_general_agent_2')
    expect(steps[1].find('.memory-chip').text()).toBe('agent')
  })

  it('渲染记忆流向图的节点与连线', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.findAll('.memory-flow__node')).toHaveLength(2)
    expect(wrapper.findAll('.memory-flow__edge')).toHaveLength(1)
  })

  it('点击其它运行切换并重新拉取记忆事件', async () => {
    const { wrapper, listEventsSpy } = await mountPage()
    await wrapper.findAll('.memory-mission__head')[1].trigger('click')
    await wrapper.findAll('.memory-mission')[1].find('.memory-run').trigger('click')
    await flushPromises()
    expect(listEventsSpy.mock.calls.at(-1)?.[0]).toBe('run_2')
  })

  it('按 Mission 分组，并将 Run 作为可折叠的二级条目展示', async () => {
    const runs = [
      makeRun({ runId: 'run_1', missionId: 'mission_a', title: '同一 Mission' }),
      makeRun({ runId: 'run_2', missionId: 'mission_a', title: '同一 Mission', status: 'failed' }),
      makeRun({ runId: 'run_3', missionId: 'mission_b', title: '另一个 Mission' })
    ]
    const missions: MissionListItem[] = [
      {
        missionId: 'mission_a', userId: 'user_1', title: '同一 Mission', description: '', status: 'active',
        latestRunId: 'run_1', latestRunStatus: 'completed', createdAt: '', updatedAt: '', runCount: 2
      },
      {
        missionId: 'mission_b', userId: 'user_1', title: '另一个 Mission', description: '', status: 'active',
        latestRunId: 'run_3', latestRunStatus: 'completed', createdAt: '', updatedAt: '', runCount: 1
      }
    ]
    const { wrapper } = await mountPage({ runs, missions })

    expect(wrapper.findAll('.memory-mission')).toHaveLength(2)
    expect(wrapper.findAll('.memory-mission__head')[0].text()).toContain('同一 Mission')
    expect(wrapper.findAll('.memory-mission__count')[0].text()).toBe('2 RUN')
    expect(wrapper.findAll('.memory-mission__runs')[0].findAll('.memory-run')).toHaveLength(2)
    expect(wrapper.findAll('.memory-run__index').map(item => item.text())).toEqual(['Run 01', 'Run 02'])

    const collapseAll = wrapper.find('.memory-runs__collapse')
    expect(collapseAll.text()).toBe('折叠全部')
    await collapseAll.trigger('click')
    expect(wrapper.findAll('.memory-mission__runs')).toHaveLength(0)
    expect(collapseAll.text()).toBe('展开全部')

    await collapseAll.trigger('click')
    expect(wrapper.findAll('.memory-mission__runs')).toHaveLength(2)

    await wrapper.findAll('.memory-mission__head')[0].trigger('click')
    expect(wrapper.find('#memory-mission-mission_a').exists()).toBe(false)
    expect(wrapper.findAll('.memory-mission__head')[0].attributes('aria-expanded')).toBe('false')
  })

  it('支持 ?runId= 直达指定运行', async () => {
    const { listEventsSpy } = await mountPage({ query: { runId: 'run_2' } })
    expect(listEventsSpy.mock.calls[0]?.[0]).toBe('run_2')
  })

  it('无运行时展示空态', async () => {
    const { wrapper } = await mountPage({ runs: [] })
    expect(wrapper.find('.memory-runs__hint').text()).toContain('暂无运行记录')
  })

  it('运行列表加载失败时展示错误与重试入口', async () => {
    vi.restoreAllMocks()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agentos/memory', name: 'MemoryCenter', component: MemoryView }]
    })
    await router.push('/agentos/memory')
    await router.isReady()
    vi.spyOn(agentosApi, 'listWorkflowRuns').mockRejectedValue(new Error('运行服务不可用'))
    const wrapper = mount(MemoryView, {
      global: { plugins: [router], stubs: { WorkbenchLayout: layoutStub, Teleport: true } }
    })
    mountedWrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.find('.memory-runs__error').text()).toContain('运行服务不可用')
    expect(wrapper.find('.memory-detail__empty--error').text()).toContain('运行记录加载失败')
    expect(wrapper.find('.memory-runs__retry').exists()).toBe(true)
  })

  it('记忆事件加载失败时展示错误与重试入口', async () => {
    vi.restoreAllMocks()
    const runs = [makeRun({ runId: 'run_1' })]
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agentos/memory', name: 'MemoryCenter', component: MemoryView }]
    })
    await router.push('/agentos/memory')
    await router.isReady()
    vi.spyOn(agentosApi, 'listWorkflowRuns').mockResolvedValue({ items: runs, total: 1, page: 1, pageSize: 50 })
    vi.spyOn(agentosApi, 'listMemoryEvents').mockRejectedValue(new Error('boom'))
    const wrapper = mount(MemoryView, {
      global: { plugins: [router], stubs: { WorkbenchLayout: layoutStub, Teleport: true } }
    })
    mountedWrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.find('.memory-detail__error').text()).toContain('boom')
    expect(wrapper.find('.memory-detail__retry').exists()).toBe(true)
  })
})
