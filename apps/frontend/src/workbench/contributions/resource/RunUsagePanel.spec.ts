import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { workflowApi, type ModelCallUsage, type RunResourceUsage } from '@/services/api/workflow'
import RunUsagePanel from './RunUsagePanel.vue'

vi.mock('@/services/api/workflow', () => ({ workflowApi: { getRunResourceUsage: vi.fn(), listRunResourceCalls: vi.fn() } }))
const usage = (tokens = 140): RunResourceUsage => ({
  runId: 'run_1', usage: { inputTokens: 100, outputTokens: 40, cacheReadTokens: 25, cacheWriteTokens: 0,
    reasoningTokens: 10, totalTokens: tokens, callCount: 2, retryCount: 0, latencyMs: 500, cacheHitRatio: 0.25 },
  contextPressure: { source: 'unknown' }, composition: {} as RunResourceUsage['composition'],
  scheduler: { activeSlots: 0, queueDepth: 0, checkpointCount: 0, recoveryCount: 0 }
})
const call = (id: string, model: string, tokens: number): ModelCallUsage => ({
  callId: id, model, provider: 'provider', latencyMs: 100, outputPolicy: 'default', outputExhausted: false,
  usage: { inputTokens: tokens, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, reasoningTokens: 0, totalTokens: tokens }
})
const wrappers: ReturnType<typeof mount>[] = []
function panel(runStatus = 'completed') {
  const wrapper = mount(RunUsagePanel, { props: { runId: 'run_1', runStatus } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(workflowApi.getRunResourceUsage).mockResolvedValue(usage())
  vi.mocked(workflowApi.listRunResourceCalls).mockResolvedValue({ runId: 'run_1', items: [], total: 0 })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers() })

describe('RunUsagePanel', () => {
  it('separates the latest input occupancy from cumulative usage and labels estimates', async () => {
    const data = usage(99999)
    data.usage.usageMissingCalls = 1
    data.contextPressure.latestRequest = { inputTokens: 123, contextWindowTokens: 10000, measurement: 'estimate' }
    vi.mocked(workflowApi.getRunResourceUsage).mockResolvedValue(data)
    const wrapper = panel()
    await flushPromises()
    expect(wrapper.find('.usage-total strong').text()).toBe('99,999')
    expect(wrapper.find('.usage-current strong').text()).toBe('123')
    expect(wrapper.find('.usage-current').text()).toContain('估算，不用于计费')
    expect(wrapper.text()).toContain('1 次调用未返回用量')
  })
  it('aggregates every ledger page without counting repeated calls or cache/reasoning twice', async () => {
    vi.mocked(workflowApi.listRunResourceCalls)
      .mockResolvedValueOnce({ runId: 'run_1', items: [call('a', 'alpha', 100)], nextCursor: 'next', total: 2 })
      .mockResolvedValueOnce({ runId: 'run_1', items: [call('a', 'alpha', 100), call('b', 'beta', 40)], total: 2 })
    const wrapper = panel()
    await flushPromises()
    expect(wrapper.find('.usage-total strong').text()).toBe('140')
    expect(wrapper.text()).toContain('25.0%')
    expect(wrapper.findAll('.token-legend dd').map(node => node.text())).toEqual(['25', '75', '40'])
    expect(wrapper.findAll('.model-usage').map(node => node.text())).toEqual([
      expect.stringContaining('71.4%'), expect.stringContaining('28.6%')
    ])
    expect(workflowApi.listRunResourceCalls).toHaveBeenLastCalledWith('run_1', { cursor: 'next', pageSize: 100 }, expect.anything())
  })

  it('keeps summary available when the model ledger fails and treats absent cache ratio as unknown', async () => {
    const data = usage()
    data.usage.cacheHitRatio = null
    vi.mocked(workflowApi.getRunResourceUsage).mockResolvedValue(data)
    vi.mocked(workflowApi.listRunResourceCalls).mockRejectedValue(new Error('offline'))
    const wrapper = panel()
    await flushPromises()
    expect(wrapper.find('.usage-total strong').text()).toBe('140')
    expect(wrapper.text()).toContain('未观测')
    expect(wrapper.text()).toContain('暂时无法读取模型调用明细')
  })

  it('shows measured cache coverage by phase and keeps unreported tokens out of misses', async () => {
    const data = usage()
    Object.assign(data.usage, { cacheHitRatio: 0.5, cacheUsageReportedCalls: 1,
      cacheMeasuredInputTokens: 50, cacheMeasuredReadTokens: 25 })
    data.cacheScopes = [
      { scope: 'node', callCount: 1, cacheUsageReportedCalls: 1, cacheHitRatio: 0.5 },
      { scope: 'planning', callCount: 1, cacheUsageReportedCalls: 0, cacheHitRatio: null },
    ]
    vi.mocked(workflowApi.getRunResourceUsage).mockResolvedValue(data)
    const wrapper = panel()
    await flushPromises()
    expect(wrapper.text()).toContain('已观测 1/2 次调用')
    const phases = wrapper.get('[aria-label="各阶段缓存命中率"]')
    expect(phases.text()).toContain('执行 Agent50.0%')
    expect(phases.text()).toContain('规划器未观测')
    expect(wrapper.findAll('.usage-chart .token-legend dd').map(node => node.text())).toEqual(['25', '25', '50', '40'])
  })

  it('discards an old run response after switching runs', async () => {
    let resolveOld!: (value: RunResourceUsage) => void
    vi.mocked(workflowApi.getRunResourceUsage).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = panel()
    await wrapper.setProps({ runId: 'run_2' })
    await flushPromises()
    resolveOld(usage(999))
    await flushPromises()
    expect(wrapper.find('.usage-total strong').text()).toBe('140')
  })

  it('refreshes active runs, marks stale stats, and stops polling on unmount', async () => {
    vi.useFakeTimers()
    const wrapper = panel('running')
    await flushPromises()
    vi.mocked(workflowApi.getRunResourceUsage).mockRejectedValueOnce(new Error('offline'))
    await vi.advanceTimersByTimeAsync(15000)
    await flushPromises()
    expect(wrapper.find('.usage-total strong').text()).toBe('140')
    expect(wrapper.text()).toContain('显示上次统计')
    expect(workflowApi.getRunResourceUsage).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(30000)
    expect(workflowApi.getRunResourceUsage).toHaveBeenCalledTimes(2)
  })
})
