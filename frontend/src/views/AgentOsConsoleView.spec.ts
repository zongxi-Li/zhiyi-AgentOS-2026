import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessageBox } from 'element-plus'
import { workflowApi, type AcgView, type WorkflowProgress, type WorkflowRun, type WorkflowRunSummary } from '@/services/api/workflow'
import WorkflowProgressBar from '@/components/agentos/WorkflowProgressBar.vue'
import WorkflowReviewPanel from '@/components/agentos/WorkflowReviewPanel.vue'
import RuntimeAuditTimeline from '@/components/agentos/RuntimeAuditTimeline.vue'
import AgentOsConsoleView from './AgentOsConsoleView.vue'

vi.mock('@/services/api/workflow', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/api/workflow')>()
  return {
    ...actual,
    workflowApi: {
      ...actual.workflowApi,
      listRuns: vi.fn(), getWorkflowProgress: vi.fn(), getRun: vi.fn(), getAcgView: vi.fn(), getIdentityHealth: vi.fn(),
      listReviews: vi.fn(), getTrace: vi.fn(), listCheckpoints: vi.fn(), startWorkflowAsync: vi.fn(),
      deleteRun: vi.fn()
    }
  }
})

const summary = (overrides: Partial<WorkflowRunSummary> = {}): WorkflowRunSummary => ({
  missionId: 'mission_1', runId: 'run_1', workflowId: 'workflow_1', status: 'running',
  phase: 'executing', message: '正在执行', percent: 50, totalSteps: 4, pendingSteps: 1,
  runningSteps: 1, waitingReviewSteps: 0, retryingSteps: 0, failedSteps: 0,
  completedSteps: 2, cancelledSteps: 0, currentStepId: 'step_3', activeStepIds: ['step_3'],
  recoveryCount: 0, startedAt: '2026-07-22T00:00:00Z', updatedAt: '2026-07-22T00:01:00Z',
  progress: 0.5, percentage: 50, createdAt: '2026-07-22T00:00:00Z', ...overrides
})
const progress = (overrides: Partial<WorkflowProgress> = {}): WorkflowProgress => ({
  ...summary(), ...overrides
})
const run: WorkflowRun = {
  runId: 'run_1', missionId: 'mission_1', workflowId: 'workflow_1', domain: 'test', status: 'completed',
  reviewMode: 'human_in_loop', input: {}, output: {}, steps: [], checkpoints: [], trace: []
}
const acg: AcgView = {
  runId: 'run_1', status: 'completed', engine: 'acg', acgBlueprint: null, completedStepIds: [],
  activeStepIds: [], stepStates: [], provenance: { productions: [], consumptions: [], interactions: [] },
  interactions: [], contractViolations: [], recoveryTrace: [], scheduleTrace: [], deliverables: [], finalReport: null,
  lowEntropyMetrics: { averageSavingRatio: 0, effectiveSavingRatio: 0, tokensAvailable: 0, tokensDelivered: 0,
    tokensSaved: 0, recoveryCount: 0, interactionCount: 0, contractViolationCount: 0, integrityStatus: 'valid' }
}

const mountConsole = async (query = '') => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agentos-console', component: { template: '<div />' } }]
  })
  await router.push(`/agentos-console${query}`)
  await router.isReady()
  const wrapper = shallowMount(AgentOsConsoleView, {
    global: { plugins: [router], stubs: { 'el-icon': true } }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('AgentOsConsoleView control plane', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('token', 'token')
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(workflowApi.listRuns).mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 50 })
    vi.mocked(workflowApi.getIdentityHealth).mockResolvedValue({
      status: 'healthy', source: 'agentos-v2', backlogCount: 0, failedCount: 0,
      oldestEventAt: null, unappliedEventCount: 0, inboxBacklog: 0, outboxBacklog: 0,
      startupReconciliation: { examinedTasks: 0, examinedRuns: 0, repairedTasks: 0, repairedRuns: 0, replayedEvents: 0, failureCount: 0 }
    })
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress())
    vi.mocked(workflowApi.getRun).mockResolvedValue(run)
    vi.mocked(workflowApi.getAcgView).mockResolvedValue(acg)
    vi.mocked(workflowApi.listReviews).mockResolvedValue({ items: [], total: 0, runId: 'run_1' })
    vi.mocked(workflowApi.getTrace).mockResolvedValue({ runId: 'run_1', missionId: 'mission_1', workflowId: 'workflow_1', domain: 'test', status: 'completed', eventCount: 0, events: [] })
    vi.mocked(workflowApi.listCheckpoints).mockResolvedValue({ items: [], total: 0, runId: 'run_1' })
    vi.mocked(workflowApi.deleteRun).mockResolvedValue({ runId: 'run_1', missionId: 'mission_1', deleted: true, missionDeleted: true })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('uses one bounded summary request and groups waiting_review first without per-item polling', async () => {
    vi.mocked(workflowApi.listRuns).mockResolvedValue({
      items: [
        summary({ runId: 'run_review', status: 'waiting_review', phase: 'review', message: '待处理' }),
        summary({ runId: 'run_active', status: 'running', phase: 'executing' }),
        summary({ runId: 'run_done', status: 'completed', phase: 'completed', percent: 100 })
      ], total: 3, page: 1, pageSize: 50
    })
    const { wrapper } = await mountConsole()

    expect(workflowApi.listRuns).toHaveBeenCalledOnce()
    expect(workflowApi.getIdentityHealth).toHaveBeenCalledOnce()
    expect(workflowApi.listRuns).toHaveBeenCalledWith(expect.objectContaining({
      statuses: expect.stringContaining('waiting_review'), summary: true, pageSize: 50
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.text().indexOf('需要处理')).toBeLessThan(wrapper.text().indexOf('正在运行'))
    expect(wrapper.findAll('.run-item-delete')).toHaveLength(0)
    expect(workflowApi.getWorkflowProgress).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps archive browsing inside the run history filters', async () => {
    const { wrapper } = await mountConsole()

    expect(wrapper.find('[aria-label="任务记录范围"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="显示当前任务"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.find('button[aria-label="显示已归档任务"]').attributes('aria-selected')).toBe('false')

    await wrapper.find('button[aria-label="显示已归档任务"]').trigger('click')
    await flushPromises()

    expect(workflowApi.listRuns).toHaveBeenLastCalledWith(
      expect.objectContaining({ recordState: 'archived' }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(wrapper.find('button[aria-label="显示已归档任务"]').attributes('aria-selected')).toBe('true')
    wrapper.unmount()
  })

  it('restores a selected Run from URL without starting a workflow or loading full ACG during planning', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress({ runId: 'run_url', phase: 'planning', percent: null }))
    const { wrapper } = await mountConsole('?runId=run_url')

    expect(workflowApi.getWorkflowProgress).toHaveBeenCalledWith('run_url', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
    expect(workflowApi.getRun).not.toHaveBeenCalled()
    expect(workflowApi.getAcgView).not.toHaveBeenCalled()
    expect(wrapper.findComponent(WorkflowProgressBar).exists()).toBe(true)
    expect(wrapper.findComponent(WorkflowReviewPanel).exists()).toBe(true)
    wrapper.unmount()
  })

  it('loads terminal Run and ACG once for the selected Run', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress({
      phase: 'completed', status: 'completed', percent: 100, completedSteps: 4
    }))
    const { wrapper } = await mountConsole('?runId=run_1')
    await flushPromises()

    expect(workflowApi.getRun).toHaveBeenCalledTimes(1)
    expect(workflowApi.getAcgView).toHaveBeenCalledTimes(1)
    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps full audit details when a terminal ACG load overlaps the detail request', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress({
      phase: 'completed', status: 'completed', percent: 100, completedSteps: 4
    }))
    let releaseFirstAcg!: () => void
    vi.mocked(workflowApi.getAcgView)
      .mockImplementationOnce(() => new Promise(resolve => {
        releaseFirstAcg = () => resolve(acg)
      }))
      .mockResolvedValue(acg)
    vi.mocked(workflowApi.getTrace).mockResolvedValue({
      runId: 'run_1', missionId: 'mission_1', workflowId: 'workflow_1', domain: 'test', status: 'completed',
      eventCount: 1, events: [{ eventId: 'trace_1', eventType: 'run_completed', payload: {} }]
    })
    const { wrapper } = await mountConsole('?runId=run_1')
    await flushPromises()

    const fullDetail = (wrapper.vm as any).loadSelectedDetail({ full: true, acg: true, review: true })
    await fullDetail
    releaseFirstAcg()
    await flushPromises()

    expect(workflowApi.getTrace).toHaveBeenCalledWith('run_1', expect.any(Object))
    expect(wrapper.findComponent(RuntimeAuditTimeline).props('events')).toEqual([
      expect.objectContaining({ eventId: 'trace_1', eventType: 'run_completed' })
    ])
    wrapper.unmount()
  })

  it('loads complete review details when waitingReviewSteps reveals a pending gate', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress({
      phase: 'executing', status: 'running', waitingReviewSteps: 1,
      currentStepId: 'human_review', activeStepIds: ['human_review']
    }))
    vi.mocked(workflowApi.getRun).mockResolvedValue({
      ...run, status: 'waiting_review',
      steps: [{ stepId: 'human_review', name: '人工审核', agentName: 'reviewer', status: 'waiting_review' }]
    })
    const { wrapper } = await mountConsole('?runId=run_1')
    await flushPromises()

    expect(workflowApi.getRun).toHaveBeenCalledWith('run_1', expect.any(Object))
    expect(workflowApi.listReviews).toHaveBeenCalledWith('run_1', expect.any(Object))
    wrapper.unmount()
  })

  it('pauses list polling while hidden and refreshes immediately when visible', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountConsole()
    expect(workflowApi.listRuns).toHaveBeenCalledTimes(1)
    expect(workflowApi.getIdentityHealth).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(14000)
    expect(workflowApi.listRuns).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(vi.mocked(workflowApi.listRuns).mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(vi.mocked(workflowApi.getIdentityHealth).mock.calls.length).toBeGreaterThanOrEqual(2)
    wrapper.unmount()
  })

  it('removes a missing URL reference and never creates a replacement Run', async () => {
    vi.mocked(workflowApi.getWorkflowProgress).mockRejectedValue(Object.assign(new Error('missing'), {
      isAxiosError: true,
      response: { status: 404 }
    }))
    const { wrapper } = await mountConsole('?runId=run_missing')
    await flushPromises()

    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('workflow.run.references.v1') || '{}').run_missing).toBeUndefined()
    expect(wrapper.findComponent(WorkflowProgressBar).exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not show a delete entry for a selected waiting review Run', async () => {
    vi.mocked(workflowApi.listRuns).mockResolvedValue({
      items: [summary({ status: 'waiting_review', phase: 'review' })],
      total: 1,
      page: 1,
      pageSize: 50
    })
    vi.mocked(workflowApi.getWorkflowProgress).mockResolvedValue(progress({
      status: 'waiting_review', phase: 'review', waitingReviewSteps: 1
    }))

    const { wrapper } = await mountConsole('?runId=run_1')
    await flushPromises()

    expect(wrapper.find('.run-item-delete').exists()).toBe(false)
    expect(wrapper.find('.run-toolbar__delete').exists()).toBe(false)
    wrapper.unmount()
  })
})
