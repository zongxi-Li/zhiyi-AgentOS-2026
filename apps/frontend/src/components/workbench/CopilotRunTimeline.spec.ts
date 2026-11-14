import { mount } from '@vue/test-utils'
import { h, reactive } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CopilotRunTimeline from './CopilotRunTimeline.vue'
import { acquireRunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import type { CopilotInitialPlan } from '@/services/api/agentos/api/copilot'
import { RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import type { RuntimeTraceObservation } from '@/workbench/runtime/observation'

vi.mock('@/workbench/runtime/runtimeEvents', async original => ({ ...await original<typeof import('@/workbench/runtime/runtimeEvents')>(), acquireRunRuntimeStore: vi.fn(), releaseRunRuntimeStore: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks() })
const plan: CopilotInitialPlan = { planVersion: 1, commitId: 'commit', commitmentRevision: 1,
  objective: '分析恢复策略', constraints: ['只做分析，不修改代码'], expectedArtifacts: ['报告'],
  tasks: [{ key: 'T1', title: '核对事实', objective: '确认输入', rationale: '为下游建立共同事实依据', acceptanceCriteria: ['标明来源'], sourceRefs: [] }] }
describe('Copilot task timeline', () => {
  it('shows public planning rationale while the model is active but has not returned any text', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running', plan,
      graphNodes: [{ acgNodeId: 'node', name: '核对事实', nodeType: 'task', displayOrder: 1, semanticTaskKey: 'T1' }],
    } }); wrappers.push(w)
    store.apply({ eventId: 'start', eventType: 'model.started', sequence: 1, runId: 'run', nodeId: 'node' })
    store.apply({ eventId: 'activity', eventType: 'model.activity', sequence: 2, runId: 'run', nodeId: 'node' })
    await w.vm.$nextTick()
    const summary = w.get('.run-timeline__output .task-work-summary')
    expect(summary.text()).toContain('确认输入')
    expect(summary.text()).toContain('为下游建立共同事实依据')
    expect(summary.text()).toContain('正文尚未返回')
    expect(w.get('.run-timeline__output').text()).toContain('等待正文')
    expect(store.nodes.node.chunkCount).toBe(0)
  })
  it('shows observed activity after reconnect without inventing a request start time', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    store.apply({ eventId: 'activity', eventType: 'model.activity', sequence: 1, runId: 'run', nodeId: 'node' })
    await w.vm.$nextTick()
    expect(w.get('.task-work-summary').text()).toContain('已收到模型活动信号')
    expect(w.get('.task-work-summary').text()).not.toContain('已等待')
  })
  it('restores recorded planning stages and a failure after mounting a terminal run', () => {
    const traces: RuntimeTraceObservation[] = [
      { kind: 'stage_completed', stage: 'decompose' },
      { kind: 'stage_completed', stage: 'repair' },
      { kind: 'failed', stage: 'repair', errorCode: 'TASK_PLAN_CONTRACT_FAILED', reasoning_content: 'PRIVATE' },
    ].map((payload, index) => ({ eventId: `record-${index}`, runId: 'run', stepId: null, eventType: 'task_status_changed',
      observation: null, timestamp: null, durationMs: null, status: null, source: 'trace', payload: { planningProgress: true, ...payload } }))
    const other = { ...traces[0], eventId: 'other', runId: 'other-run', payload: { planningProgress: true, kind: 'plan_parsed', taskCount: 999 } }
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'failed', traces: [...traces, other] } }); wrappers.push(w)
    expect(w.find('.run-timeline__planning-history').exists()).toBe(false)
    expect(w.findAll('.run-timeline__progress > p').map(p => p.text())).toEqual([
      '已生成任务步骤与规划依据，后续还需校验是否满足任务约束。',
      '本轮规划修正已生成，仍需通过校验后才能进入执行。',
      '本次规划未完成，暂时无法进入执行。',
    ])
    expect(w.text()).toContain('TASK_PLAN_CONTRACT_FAILED')
    expect(w.text()).not.toContain('PRIVATE')
    expect(w.text()).not.toContain('999')
    expect(acquireRunRuntimeStore).not.toHaveBeenCalled()
    expect(w.emitted('content')?.at(-1)).toEqual([true])
  })
  it('shows public planning text and rationale while the run-scoped model is still streaming', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'planning' } }); wrappers.push(w)
    let sequence = 0
    const apply = (eventType: string, payload: Record<string, unknown> = {}) => store.apply({ eventId: `planning-${++sequence}`, sequence,
      eventType, runId: 'run', nodeId: null, attemptId: null, payload })
    apply('planner.stage.started', { stage: 'intent_profile', callKey: 'intent_profile' })
    apply('planner.model.output.delta', { stage: 'intent_profile', callKey: 'intent_profile',
      delta: '{"reasoning_content":"PRIVATE","primaryGoal":"设计实验室管理平台","keyConstraints":["覆盖三个校区"]}' })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__planning-text').text()).toContain('设计实验室管理平台')
    expect(w.text()).toContain('理解目标与约束')
    expect(w.text()).not.toContain('PRIVATE')
    apply('planner.profile.resolved', { constraintCount: 7, requiredCapabilityCount: 9, expectedArtifactCount: 2 })
    apply('planner.stage.started', { stage: 'decompose', callKey: 'decompose' })
    apply('planner.model.output.delta', { stage: 'decompose', callKey: 'decompose',
      delta: '{"tasks":[{"key":"internal-key","title":"核对需求","objective":"明确跨校区的数据边界","decompositionRationale":"先统一数据口径，再设计权限' })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__planning-text').text()).toContain('先统一数据口径，再设计权限')
    expect(w.text()).toContain('拆分任务与规划依据')
    expect(w.text()).toContain('7 项约束')
    expect(w.text()).toContain('9 项能力')
    expect(w.text()).not.toContain('internal-key')
    expect(w.text()).not.toContain('decompositionRationale')
    expect(w.emitted('content')?.at(-1)).toEqual([true])
    expect(store.planning.modelPhase).toBe('ACTIVE')
    apply('planner.failed', { errorCode: 'MODEL_OUTPUT_INVALID_JSON' })
    await w.setProps({ status: 'failed' })
    expect(w.get('.run-timeline__planning-text').text()).toContain('先统一数据口径')
    expect(w.text()).toContain('本次规划未完成')
  })
  it('opens the task draft and shows its public rationale before plan acceptance', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'planning' } }); wrappers.push(w)
    store.apply({ eventId: 'draft', sequence: 1, eventType: 'planner.draft.updated', runId: 'run',
      payload: { stage: 'detail', nodes: [{ key: 'T1', title: '核对数据范围', rationale: '先核对需求再建立模型' }] } })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__draft').attributes('open')).toBeDefined()
    expect(w.get('.run-timeline__draft').text()).toContain('先核对需求再建立模型')
  })
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
  it('retains each public work explanation between actual tool calls in the same step', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    let sequence = 0
    const apply = (eventType: string, payload: Record<string, unknown> = {}) => {
      sequence++
      store.apply({ eventId: `work-${sequence}`, sequence, eventType, runId: 'run', nodeId: 'node', attemptId: 'attempt',
        timestamp: `2026-11-14T10:00:${String(sequence).padStart(2, '0')}Z`, payload })
    }
    apply('model.started', { nodeTitle: '检查加载问题' })
    apply('model.output.delta', { delta: '{"reasoning_content":"PRIVATE","summary":"先读取事件处理代码，确认按钮是否触发请求。"}' })
    apply('model.completed')
    apply('tool.execution_started', { tool: 'fs.read' })
    apply('tool.execution_completed', { tool: 'fs.read', executionId: 'read', status: 'completed', receiptRef: 'file-receipt' })
    apply('model.started', { nodeTitle: '检查加载问题' })
    apply('model.output.delta', { delta: '{"summary":"读取结果显示已有事件处理，下一步检查请求返回。"}' })
    apply('model.completed')
    // All events can arrive before Vue paints; the earlier explanation must survive.
    await w.vm.$nextTick()
    const rows = Array.from(w.element.children).filter(el => el.matches('article, details'))
    expect(rows).toHaveLength(3)
    expect(rows[0].textContent).toContain('先读取事件处理代码')
    expect(rows[1].className).toBe('run-timeline__tools')
    expect(rows[2].textContent).toContain('读取结果显示已有事件处理')
    expect(w.text()).not.toContain('PRIVATE')
    expect(w.findAll('.run-timeline__output')).toHaveLength(2)
    expect(w.text()).not.toContain('正在生成')
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
    expect(w.findAll('.run-timeline__tool summary').map(item => item.text())).toEqual(['查看目录已完成', '查看目录执行中'])
  })
  it('groups adjacent tool operations while keeping intervening messages in time order', () => {
    const at = (seconds: number) => `2026-11-14T10:00:${String(seconds).padStart(2, '0')}Z`
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'completed', startedAt: at(0), updatedAt: at(57),
      tools: [
        { executionId: 'read', tool: 'fs.read', stepId: 'step', attemptId: 'attempt', status: 'completed', createdAt: at(1), receiptRef: 'read-evidence' },
        { executionId: 'shell', tool: 'shell.exec', stepId: 'step', attemptId: 'attempt', status: 'failed', createdAt: at(2), receiptRef: 'shell-evidence' },
        { executionId: 'next', tool: 'fs.patch', stepId: 'step', attemptId: 'attempt', status: 'completed', createdAt: at(8) },
      ],
      messages: [{ id: 'user', role: 'user', content: '先检查测试结果', time: at(5), planner: false, proposalId: '' }],
    }, slots: { message: ({ message }) => h('article', { class: 'test-message' }, message.content) } }); wrappers.push(w)
    const groups = w.findAll('.run-timeline__tools')
    expect(groups).toHaveLength(2)
    expect(groups[0].get('.run-timeline__operation-summary').text()).toBe('读取文件、运行命令2 项失败')
    expect(groups[0].attributes('open')).toBeUndefined()
    expect(groups[0].findAll('.run-timeline__tool')).toHaveLength(2)
    expect(groups[0].text()).toContain('shell-evidence')
    expect(groups[1].get('.run-timeline__operation-summary').text()).toBe('修改文件已完成')
    expect(Array.from(w.element.children).filter(el => el.matches('details, article')).map(el => el.className)).toEqual([
      'run-timeline__tools', 'test-message', 'run-timeline__tools',
    ])
    expect(w.get('.run-timeline__status').text()).toContain('用时 57 秒')
  })
  it('keeps the reviewed plan, chat and approval controls visible when work history is collapsed', async () => {
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'pending', plan,
      tools: [{ executionId: 'exec', tool: 'fs.list', stepId: 'step', status: 'completed', createdAt: '' }],
      messages: [{ id: 'user', role: 'user', content: '请等待我的确认', time: '', planner: false, proposalId: '' }],
    }, slots: {
      message: ({ message }) => h('article', { class: 'test-message' }, message.content),
      controls: '<button class="test-confirm">确认规划</button>', approvals: '<button class="test-approval">批准工具操作</button>',
    } }); wrappers.push(w)
    const toggle = w.get('.run-timeline__history-toggle')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.get('.run-timeline__operation-summary').isVisible()).toBe(false)
    expect(w.get('.run-timeline__plan').isVisible()).toBe(true)
    expect(w.get('.test-message').isVisible()).toBe(true)
    expect(w.get('.test-confirm').isVisible()).toBe(true)
    expect(w.get('.test-approval').isVisible()).toBe(true)
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    // VTU treats a closed native <details> as hidden, including its summary.
    expect((w.get('.run-timeline__tools').element as HTMLElement).style.display).not.toBe('none')
    await w.setProps({ runId: 'next' })
    expect(toggle.attributes('aria-expanded')).toBe('true')
  })
})
