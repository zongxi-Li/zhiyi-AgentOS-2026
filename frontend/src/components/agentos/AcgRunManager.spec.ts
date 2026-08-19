import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import AcgRunManager from './AcgRunManager.vue'
import { workflowApi, type WorkflowRunSummary } from '@/services/api/workflow'
import { ElMessageBox } from 'element-plus'
import { ACG_HISTORY_SOURCES } from '@/utils/acgHistoryFilter'

vi.mock('@/services/api/workflow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/api/workflow')>()
  return {
    ...actual,
    workflowApi: {
      ...actual.workflowApi,
      listRuns: vi.fn(),
      deleteRun: vi.fn()
    }
  }
})

const run = (overrides: Partial<WorkflowRunSummary>): WorkflowRunSummary => ({
  taskId: `task_${overrides.runId || 'run_active_123456789'}`, runId: 'run_active_123456789', workflowId: 'legal_contract_review_v1',
  title: '请以 ACG 多智能体协作方式审查这份软件开发合同，强制生成差异化任务图，并完整执行后续流程。', status: 'running', phase: 'executing', message: '风险识别',
  percent: 28, totalSteps: 7, pendingSteps: 4, runningSteps: 1, waitingReviewSteps: 0,
  retryingSteps: 0, failedSteps: 0, completedSteps: 2, cancelledSteps: 0,
  currentStepId: 'risk_detect', activeStepIds: ['risk_detect'], recoveryCount: 0,
  startedAt: '2026-07-26T04:00:00Z', updatedAt: '2026-07-26T04:00:14Z',
  progress: 28, percentage: 28, source: 'acg', createdAt: '2026-07-26T04:00:00Z',
  ...overrides
})

describe('AcgRunManager', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.mocked(workflowApi.listRuns).mockResolvedValue({
      items: [
        run({}),
        run({ runId: 'run_review_1', title: '数据合规风险评估', status: 'waiting_review', phase: 'review', percent: 75 }),
        run({ runId: 'run_done_1', title: '采购合同条款分析', status: 'completed', phase: 'completed', percent: 100 })
      ],
      total: 3, page: 1, pageSize: 100
    })
    vi.mocked(workflowApi.deleteRun).mockResolvedValue({
      runId: 'run_done_1',
      taskId: 'task_1',
      deleted: true,
      taskDeleted: true
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('loads ACG summaries and renders flat status groups', async () => {
    const wrapper = mount(AcgRunManager, {
      props: { activeRunId: 'run_active_123456789' },
      global: { stubs: { 'el-icon': true } }
    })
    await flushPromises()

    expect(workflowApi.listRuns).toHaveBeenCalledWith(
      expect.objectContaining({
        sources: ACG_HISTORY_SOURCES,
        statuses: expect.stringContaining('waiting_review'),
        summary: true,
        pageSize: 20
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(wrapper.text()).toContain('运行中')
    expect(wrapper.text()).toContain('等待审核')
    expect(wrapper.text()).toContain('最近完成')
    expect(wrapper.find('.acg-run-item.active').exists()).toBe(true)
    expect(wrapper.find('.acg-run-item__headline strong').text()).toBe('软件开发合同审查')
    expect(wrapper.find('.acg-run-item__meta').text()).toContain('步骤 2/7')
    expect(wrapper.find('.acg-run-item__meta time').text()).toMatch(/^(?:更新于|完成于) /)
    wrapper.unmount()
  })

  it('filters the combined ACG history by role domain', async () => {
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    await wrapper.find('select[aria-label="按角色筛选 ACG 记录"]').setValue('lawyer')
    await flushPromises()

    expect(workflowApi.listRuns).toHaveBeenLastCalledWith(
      expect.objectContaining({ sources: ACG_HISTORY_SOURCES, domain: 'legal' }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(localStorage.getItem('acg.history.role')).toBe('lawyer')
    wrapper.unmount()
  })

  it('shows only the latest run for the same task and moves it to the latest status group', async () => {
    vi.mocked(workflowApi.listRuns).mockResolvedValue({
      items: [
        run({ taskId: 'task_retry', runId: 'run_failed', status: 'failed', phase: 'failed', updatedAt: '2026-07-26T04:00:10Z' }),
        run({ taskId: 'task_retry', runId: 'run_success', status: 'completed', phase: 'completed', updatedAt: '2026-07-26T04:01:10Z' })
      ],
      total: 2, page: 1, pageSize: 20
    })
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    expect(wrapper.findAll('.acg-run-item')).toHaveLength(1)
    expect(wrapper.find('.status-completed').exists()).toBe(true)
    expect(wrapper.find('.status-failed').exists()).toBe(false)
    expect(wrapper.find('.acg-run-item__select').attributes('title')).toContain('task_retry')
    wrapper.unmount()
  })

  it('sorts each status group by the authoritative update timestamp', async () => {
    vi.mocked(workflowApi.listRuns).mockResolvedValue({
      items: [
        run({ taskId: 'task_older', runId: 'run_older', title: '较早任务', updatedAt: '2026-07-26T04:00:10Z' }),
        run({ taskId: 'task_newer', runId: 'run_newer', title: '较新任务', updatedAt: '2026-07-26T04:02:10Z' })
      ],
      total: 2,
      page: 1,
      pageSize: 20
    })
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    expect(wrapper.findAll('.acg-run-item__headline strong').map(item => item.text())).toEqual(['较新任务', '较早任务'])
    wrapper.unmount()
  })

  it('labels same-day timestamps as update time instead of an ambiguous duration', async () => {
    vi.setSystemTime(new Date('2026-07-26T04:30:00Z'))
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    expect(wrapper.find('.status-active .acg-run-item__meta time').text()).toContain('更新于 今天')
    expect(wrapper.find('.status-active .acg-run-item__meta time').attributes('title')).toContain('最后更新')
    wrapper.unmount()
  })

  it('keeps the previous list visible and coalesces overlapping refresh events', async () => {
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    let resolveRefresh!: (value: Awaited<ReturnType<typeof workflowApi.listRuns>>) => void
    vi.mocked(workflowApi.listRuns).mockImplementationOnce(() => new Promise(resolve => {
      resolveRefresh = resolve
    }))

    window.dispatchEvent(new Event('acg-runs-refresh'))
    window.dispatchEvent(new Event('acg-runs-refresh'))
    await Promise.resolve()

    expect(workflowApi.listRuns).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('.acg-run-item')).toHaveLength(3)
    expect(wrapper.find('.acg-run-refreshing').exists()).toBe(true)
    expect(wrapper.find('.acg-run-message').exists()).toBe(false)

    resolveRefresh({
      items: [run({ runId: 'run_fresh_1', title: 'Fresh run' })],
      total: 1,
      page: 1,
      pageSize: 20
    })
    await flushPromises()

    expect(wrapper.findAll('.acg-run-item')).toHaveLength(1)
    expect(wrapper.find('.acg-run-refreshing').exists()).toBe(false)
    wrapper.unmount()
  })

  it('schedules the next poll only after the current request settles', async () => {
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    let resolvePoll!: (value: Awaited<ReturnType<typeof workflowApi.listRuns>>) => void
    vi.mocked(workflowApi.listRuns).mockImplementationOnce(() => new Promise(resolve => {
      resolvePoll = resolve
    }))

    vi.advanceTimersByTime(8_000)
    await Promise.resolve()
    expect(workflowApi.listRuns).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(16_000)
    await Promise.resolve()
    expect(workflowApi.listRuns).toHaveBeenCalledTimes(2)

    resolvePoll({ items: [run({})], total: 1, page: 1, pageSize: 20 })
    await flushPromises()
    vi.advanceTimersByTime(8_000)
    await flushPromises()
    expect(workflowApi.listRuns).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('emits draft creation and run selection without creating a run itself', async () => {
    const wrapper = mount(AcgRunManager, { global: { stubs: { 'el-icon': true } } })
    await flushPromises()

    await wrapper.find('.acg-new-run').trigger('click')
    await wrapper.find('.acg-run-item__select').trigger('click')

    expect(wrapper.emitted('new')).toHaveLength(1)
    expect(wrapper.emitted('select')?.[0]).toEqual(['run_active_123456789'])
    expect(workflowApi.listRuns).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

})
