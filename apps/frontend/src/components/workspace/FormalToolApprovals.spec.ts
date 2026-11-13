import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FormalToolApprovals from './FormalToolApprovals.vue'
import { agentosRequest } from '@/services/api/agentos/client'
import { acquireRunRuntimeStore, releaseRunRuntimeStore } from '@/workbench/runtime/runtimeEvents'

vi.mock('@/services/api/agentos/client', () => ({ agentosRequest: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/workbench/runtime/runtimeEvents', () => ({ acquireRunRuntimeStore: vi.fn(), releaseRunRuntimeStore: vi.fn() }))
const approval = { approvalId: 'approval', operationSummary: 'Run command: inspect', command: 'inspect', relativePath: '.' }
const wrappers: ReturnType<typeof mount>[] = []
let events: { activity: { approvalRevision: number } }
beforeEach(() => {
  vi.clearAllMocks()
  events = reactive({ activity: { approvalRevision: 0 } })
  vi.mocked(acquireRunRuntimeStore).mockReturnValue(events as any)
  vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [] } })
  vi.mocked(agentosRequest.post).mockResolvedValue({ data: { resolved: true } })
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.useRealTimers() })
async function render(extra = {}) {
  const w = mount(FormalToolApprovals, { props: { runId: 'run', active: true, ...extra } })
  wrappers.push(w); await flushPromises(); return w
}
describe('inline formal tool approval', () => {
  it('keeps an approval visible while authority is synchronizing, then permits one explicit decision', async () => {
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [approval] } })
    const w = await render({ readonly: true })
    expect(w.text()).toContain('等待你确认')
    expect(w.get('pre').text()).toBe('inspect')
    expect(w.findAll('.tool-approvals__actions button').every(b => b.attributes('disabled') !== undefined)).toBe(true)
    await w.setProps({ readonly: false })
    let finish!: (value: any) => void
    vi.mocked(agentosRequest.post).mockReturnValue(new Promise(resolve => { finish = resolve }))
    await w.get('.tool-approvals__actions button').trigger('click')
    await w.get('.tool-approvals__actions button').trigger('click')
    expect(agentosRequest.post).toHaveBeenCalledOnce()
    expect(agentosRequest.post).toHaveBeenCalledWith('/runs/run/tool-approvals/approval', { decision: 'allow_once' })
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [] } })
    finish({ data: { resolved: true } }); await flushPromises()
    expect(w.find('article').exists()).toBe(false)
    expect(w.emitted('resolved')).toHaveLength(1)
  })
  it('refreshes from an SSE invalidation and reconnect rather than a polling timer', async () => {
    vi.useFakeTimers()
    const w = await render()
    await vi.advanceTimersByTimeAsync(10000)
    expect(agentosRequest.get).toHaveBeenCalledTimes(1)
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [approval] } })
    events.activity.approvalRevision++; await flushPromises()
    expect(w.find('article').exists()).toBe(true)
    expect(w.emitted('waiting')?.at(-1)).toEqual([true])
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [] } })
    events.activity.approvalRevision++; await flushPromises()
    expect(w.find('article').exists()).toBe(false)
  })
  it('rejects stale responses when switching runs or entering a terminal state', async () => {
    let old!: (value: any) => void
    vi.mocked(agentosRequest.get).mockReturnValueOnce(new Promise(resolve => { old = resolve }))
    const w = await render()
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [{ ...approval, approvalId: 'new', operationSummary: 'new run' }] } })
    await w.setProps({ runId: 'other' }); await flushPromises()
    old({ data: { items: [approval] } }); await flushPromises()
    expect(w.text()).toContain('new run')
    expect(w.text()).not.toContain('Run command: inspect')
    await w.setProps({ active: false }); await flushPromises()
    expect(w.find('article').exists()).toBe(false)
    expect(releaseRunRuntimeStore).toHaveBeenCalled()
    expect(agentosRequest.post).not.toHaveBeenCalled()
  })
  it('keeps the latest same-run snapshot when earlier GETs finish out of order', async () => {
    let old!: (value: any) => void
    vi.mocked(agentosRequest.get).mockReturnValueOnce(new Promise(resolve => { old = resolve }))
    const w = await render()
    const oldRequest = vi.mocked(agentosRequest.get).mock.calls[0][1]
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [] } })
    events.activity.approvalRevision++; await flushPromises()
    expect(oldRequest?.signal?.aborted).toBe(true)
    old({ data: { items: [approval] } }); await flushPromises()
    expect(w.find('article').exists()).toBe(false)
    expect(w.emitted('waiting')?.at(-1)).not.toEqual([true])
  })
})
