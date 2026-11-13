import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CopilotRunTimeline from './CopilotRunTimeline.vue'
import { acquireRunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import type { CopilotInitialPlan } from '@/services/api/agentos/api/copilot'
import { RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'

vi.mock('@/workbench/runtime/runtimeEvents', async original => ({ ...await original<typeof import('@/workbench/runtime/runtimeEvents')>(), acquireRunRuntimeStore: vi.fn(), releaseRunRuntimeStore: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks() })
const plan: CopilotInitialPlan = { planVersion: 1, commitId: 'commit', commitmentRevision: 1,
  objective: '分析恢复策略', constraints: ['只做分析，不修改代码'], expectedArtifacts: ['报告'],
  tasks: [{ key: 'T1', title: '核对事实', objective: '确认输入', rationale: '为下游建立共同事实依据', acceptanceCriteria: ['标明来源'], sourceRefs: [] }] }
describe('Copilot task timeline', () => {
  it('renders each public delta before the model finishes and retains the preview after run completion', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    let sequence = 0
    const apply = (eventType: string, payload: Record<string, unknown> = {}) => store.apply({ eventId: `stream-${++sequence}`, sequence,
      eventType, runId: 'run', nodeId: 'node', attemptId: 'attempt', payload })
    apply('model.started', { nodeTitle: '第一轮验收核查', model: 'test' })
    apply('model.output.delta', { delta: '{"reasoning_content":"PRIVATE","answer":"已检查' })
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(w.get('.run-timeline__output').text()).toContain('已检查')
    expect(w.get('.run-timeline__output').text()).toContain('正在生成')
    expect(w.text()).not.toContain('PRIVATE')
    expect(store.nodes.node.phase).toBe('STREAMING')
    apply('model.output.delta', { delta: '，找到两项问题"}' })
    apply('model.completed')
    apply('node.completed')
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__text').text()).toContain('已检查，找到两项问题')
    await w.setProps({ status: 'completed' })
    expect(w.text()).toContain('已检查，找到两项问题')
    expect(w.text()).toContain('完整结果以步骤交付为准')
    expect(w.emitted('content')).toBeTruthy()
  })
  it('renders the frozen plan, public rationale and receipts for an existing failed run', () => {
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'failed', plan,
      tools: [{ executionId: 'exec', tool: 'fs.list', status: 'completed', stepId: 'step', createdAt: '', receiptRef: 'receipt' }] },
      slots: { controls: '<button>确认规划</button>' } })
    wrappers.push(w)
    expect(w.text()).toContain('初步规划')
    expect(w.text()).toContain('为下游建立共同事实依据')
    expect(w.text()).toContain('只做分析，不修改代码')
    expect(w.get('.run-timeline__tool summary').text()).toContain('查看目录')
    expect(w.text()).toContain('receipt')
    expect(acquireRunRuntimeStore).not.toHaveBeenCalled()
  })
  it('shows live tool progress once and makes the human wait explicit', async () => {
    const store = { activity: reactive({ events: [] as any[], approvalRevision: 0 }), planning: reactive({ stage: null, draft: { nodes: [] } }) }
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store as any)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    store.activity.events.push({ eventId: 'start', eventType: 'tool.execution_started', nodeId: 'step', attemptId: 'attempt', payload: { tool: 'fs.list' } })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__tool summary').text()).toContain('执行中')
    store.activity.events.push({ eventId: 'done', eventType: 'tool.execution_completed', nodeId: 'step', attemptId: 'attempt', payload: { tool: 'fs.list', executionId: 'exec', status: 'completed' } })
    await w.vm.$nextTick()
    expect(w.findAll('.run-timeline__tool')).toHaveLength(1)
    expect(w.get('.run-timeline__tool summary').text()).toContain('已完成')
    await w.setProps({ waitingForApproval: true })
    expect(w.get('[role="status"]').text()).toContain('等待你确认')
  })
  it('reconciles a completed snapshot without hiding a later call of the same tool', async () => {
    const store = { activity: reactive({ events: [{ eventId: 'start', eventType: 'tool.execution_started', nodeId: 'step', attemptId: 'attempt', timestamp: '2026-11-13T10:00:00Z', payload: { tool: 'fs.list' } }] as any[], approvalRevision: 0 }), planning: reactive({ stage: null, draft: { nodes: [] } }) }
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store as any)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    expect(w.get('.run-timeline__tool summary').text()).toContain('执行中')
    await w.setProps({ tools: [{ executionId: 'exec', tool: 'fs.list', status: 'completed', stepId: 'step', attemptId: 'attempt', createdAt: '2026-11-13T10:00:01Z', receiptRef: 'receipt' }] })
    expect(w.findAll('.run-timeline__tool')).toHaveLength(1)
    expect(w.get('.run-timeline__tool summary').text()).toContain('已完成')
    expect(w.text()).toContain('receipt')

    store.activity.events.push({ eventId: 'next', eventType: 'tool.execution_started', nodeId: 'step', attemptId: 'attempt', timestamp: '2026-11-13T10:00:02Z', payload: { tool: 'fs.list' } })
    await w.vm.$nextTick()
    expect(w.findAll('.run-timeline__tool')).toHaveLength(2)
    expect(w.findAll('.run-timeline__tool summary').map(item => item.text())).toEqual(['›查看目录已完成', '›查看目录执行中'])
  })
})
