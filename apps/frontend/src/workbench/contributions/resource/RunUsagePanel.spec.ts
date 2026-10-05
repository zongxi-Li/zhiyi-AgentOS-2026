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
