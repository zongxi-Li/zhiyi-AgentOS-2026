import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  workflowApi,
  type AcgView,
  type WorkflowProgress,
  type WorkflowRun
} from '@/services/api/workflow'
import WorkflowProgressBar from '@/components/agentos/WorkflowProgressBar.vue'
import AgentOsRunSummaryCard from '@/components/agentos/AgentOsRunSummaryCard.vue'
import AcgVisualizationView from './AcgVisualizationView.vue'

vi.mock('@/services/api/workflow', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/api/workflow')>()
  return {
    ...actual,
    workflowApi: {
      ...actual.workflowApi,
      startWorkflowAsync: vi.fn(),
      rerunWorkflowAsync: vi.fn(),
      getWorkflowProgress: vi.fn(),
      getRun: vi.fn(),
      getRunHistoryConfig: vi.fn(),
      getAcgView: vi.fn()
    }
  }
})

const progress = (overrides: Partial<WorkflowProgress> = {}): WorkflowProgress => ({
  missionId: 'mission_1', runId: 'run_1', workflowId: 'native_acg_runtime_v1', status: 'running',
  phase: 'executing', message: '正在执行节点', percent: 50, totalSteps: 4, pendingSteps: 1,
  runningSteps: 1, waitingReviewSteps: 0, retryingSteps: 0, failedSteps: 0,
  completedSteps: 2, cancelledSteps: 0, currentStepId: 'step_3', activeStepIds: ['step_3'],
  recoveryCount: 0, startedAt: '2026-08-20T00:00:00Z', updatedAt: '2026-08-20T00:01:00Z',
  progress: 0.5, percentage: 50, ...overrides
})

const run = (overrides: Partial<WorkflowRun> = {}): WorkflowRun => ({
  runId: 'run_1', missionId: 'mission_1', workflowId: 'native_acg_runtime_v1', domain: 'general',
  title: '测试 ACG 任务', status: 'running', steps: [], activeStepIds: ['step_3'],
  lifecyclePhase: 'executing', lifecycleMessage: '正在执行节点', ...overrides
})

const acg = (overrides: Partial<AcgView> = {}): AcgView => ({
  runId: 'run_1', status: 'running', engine: 'acg', acgBlueprint: null, graphVersion: 1,
  completedStepIds: [], activeStepIds: ['step_3'], stepStates: [],
  provenance: { productions: [], consumptions: [], interactions: [] }, interactions: [],
  contractViolations: [], recoveryTrace: [], scheduleTrace: [], deliverables: [], finalReport: null,
  lowEntropyMetrics: { averageSavingRatio: 0, effectiveSavingRatio: 0, tokensAvailable: 0,
    tokensDelivered: 0, tokensSaved: 0, recoveryCount: 0, interactionCount: 0,
    contractViolationCount: 0, integrityStatus: 'valid' },
  ...overrides
})

const buttonStub = {
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>'
}

const mountPage = async (query = ''): Promise<{ wrapper: VueWrapper; router: Router }> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/agentos/acg', component: { template: '<div />' } },
      { path: '/agentos-console', component: { template: '<div />' } }
    ]
  })
  await router.push(`/agentos/acg${query}`)
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = shallowMount(AcgVisualizationView, {
    global: {
      plugins: [pinia, router],
      stubs: {
        'el-button': buttonStub,
        'el-icon': true,
        'el-input': true,
        'el-input-number': true,
        'el-tag': { template: '<span><slot /></span>' },
        'el-drawer': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<div v-if="modelValue"><slot name="header" /><slot /></div>'
        },
        'el-radio-group': true,
        'el-radio-button': true,
        'el-switch': true,
        'el-checkbox': true,
        'el-checkbox-group': true,
        'el-select': true,
        'el-option': true
      }
    }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('AcgVisualizationView 执行运行时 page wiring', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress())
    vi.mocked(workflowApi.getRun).mockResolvedValue(run())
    vi.mocked(workflowApi.getAcgView).mockResolvedValue(acg())
    vi.mocked(workflowApi.getRunHistoryConfig).mockResolvedValue({
      runId: 'run_1', title: '测试 ACG 任务', reviewMode: 'auto', enabledPluginIds: [], input: {}
    })
    vi.mocked(workflowApi.startWorkflowAsync).mockResolvedValue(run({ status: 'pending', lifecyclePhase: 'planning' }))
    vi.mocked(workflowApi.rerunWorkflowAsync).mockResolvedValue(run({
      runId: 'run_2', missionId: 'mission_1', status: 'pending', lifecyclePhase: 'planning'
    }))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('renders the native workbench without inventing a Run before submission', async () => {
    const { wrapper } = await mountPage()

    expect(wrapper.find('.hero-left').text()).toContain('ACG 动态群体智能引擎')
    expect(wrapper.find('.hero-run-chip').exists()).toBe(false)
    expect(wrapper.text()).toContain('任务定义')
    expect(wrapper.findComponent(WorkflowProgressBar).exists()).toBe(false)
    expect(workflowApi.getWorkflowProgress).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens advanced run settings as a downward popover without changing the primary controls', async () => {
    const { wrapper } = await mountPage()

    expect(wrapper.find('.advanced-settings').exists()).toBe(false)
    await wrapper.find('.advanced-toggle').trigger('click')
    await flushPromises()

    expect(wrapper.find('.advanced-toggle').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.primary-options .primary-config').exists()).toBe(true)
    await wrapper.find('.advanced-toggle').trigger('click')
    expect(wrapper.find('.advanced-toggle').attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })

  it('restores a URL Run and keeps the progress and 执行运行时 summary visible', async () => {
    const { wrapper } = await mountPage('?runId=run_1')

    expect(workflowApi.getWorkflowProgress).toHaveBeenCalledWith(
      'run_1', expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
    expect(wrapper.findComponent(WorkflowProgressBar).exists()).toBe(true)
    expect(wrapper.findComponent(AgentOsRunSummaryCard).exists()).toBe(true)
    expect(wrapper.text()).toContain('mission_1')
    wrapper.unmount()
  })

  it('keeps the Mission ID visible when the ACG projection fails', async () => {
    vi.mocked(workflowApi.getAcgView).mockRejectedValue(Object.assign(new Error('subresource missing'), {
      isAxiosError: true,
      response: { status: 404 }
    }))

    const { wrapper, router } = await mountPage('?runId=run_1')

    expect(wrapper.find('.hero-run-chip').text()).toContain('任务 ID')
    expect(wrapper.find('.hero-run-chip').text()).toContain('mission_1')
    expect(router.currentRoute.value.query.runId).toBe('run_1')
    wrapper.unmount()
  })

  it('starts a Run, writes its id to the URL and immediately connects progress polling', async () => {
    const { wrapper, router } = await mountPage()
    const draft = (wrapper.vm as unknown as { draft: { title: string; taskGoal: string } }).draft
    draft.title = '测试任务实施方案'
    draft.taskGoal = '输出可验收的实施方案'
    await wrapper.vm.$nextTick()

    const startButton = wrapper.findAll('button').find(item => item.text().includes('启动 ACG'))
    expect(startButton).toBeTruthy()
    await startButton!.trigger('click')
    await flushPromises()

    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledWith(
      expect.objectContaining({ title: '测试任务实施方案', domain: 'general' }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(workflowApi.getWorkflowProgress).toHaveBeenCalledWith(
      'run_1', expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(router.currentRoute.value.query.runId).toBe('run_1')
    expect(wrapper.findComponent(WorkflowProgressBar).exists()).toBe(true)
    wrapper.unmount()
  })

  it('reruns the current configuration as a new Run under the same Mission', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress({
      status: 'completed', phase: 'completed', percent: 100
    }))
    vi.mocked(workflowApi.getRun).mockResolvedValue(run({
      status: 'completed', lifecyclePhase: 'completed'
    }))
    const { wrapper, router } = await mountPage('?runId=run_1')
    const draft = (wrapper.vm as unknown as { draft: { title: string; taskGoal: string } }).draft
    draft.title = '测试任务实施方案'
    draft.taskGoal = '输出可验收的实施方案'
    await wrapper.vm.$nextTick()

    const rerunButton = wrapper.findAll('button').find(item => item.text().includes('基于当前配置重新运行'))
    expect(rerunButton).toBeTruthy()
    await rerunButton!.trigger('click')
    await flushPromises()

    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
    expect(workflowApi.rerunWorkflowAsync).toHaveBeenCalledWith(
      'mission_1',
      expect.objectContaining({
        sourceRunId: 'run_1',
        rerunReason: 'current_configuration',
        input: expect.objectContaining({ taskName: '测试任务实施方案' })
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(router.currentRoute.value.query.runId).toBe('run_2')
    wrapper.unmount()
  })

  it('removes a missing URL Run instead of leaving a stale progress shell', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockRejectedValue(Object.assign(new Error('missing'), {
      isAxiosError: true,
      response: { status: 404 }
    }))
    const { wrapper, router } = await mountPage('?runId=run_missing')
    await flushPromises()

    expect(router.currentRoute.value.query.runId).toBeUndefined()
    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
    expect(wrapper.findComponent(WorkflowProgressBar).exists()).toBe(false)
    wrapper.unmount()
  })
})
