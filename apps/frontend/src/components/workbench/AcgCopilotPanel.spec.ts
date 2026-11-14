import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AcgCopilotPanel from './AcgCopilotPanel.vue'
import { agentosApi } from '@/services/api/agentos'
import type { CopilotState } from '@/services/api/agentos/api/copilot'
import { clearCopilotSession } from './copilotSessionCache'
import FormalExecutionControls from '@/components/workspace/FormalExecutionControls.vue'
import FormalToolApprovals from '@/components/workspace/FormalToolApprovals.vue'
import { capabilitiesFixture } from '@/test/fixtures/runCapabilities'

vi.mock('@/services/api/agentos', () => ({ agentosApi: { getCopilot: vi.fn(), setCopilotPermission: vi.fn(), streamCopilotMessage: vi.fn(), answerPlanner: vi.fn(), listRunResourceCalls: vi.fn(), previewCopilotAction: vi.fn(), applyCopilotAction: vi.fn(), applyWorkflowReview: vi.fn(), submitFormalControl: vi.fn() } }))
vi.mock('@/services/api/agentos/client', () => ({ agentosRequest: { get: vi.fn(async () => ({ data: { items: [] } })), post: vi.fn() } }))
vi.mock('@/workbench/runtime/runtimeEvents', () => ({ acquireRunRuntimeStore: vi.fn(() => null), releaseRunRuntimeStore: vi.fn() }))
const state = (): CopilotState => ({ runId: 'run-1', status: 'running', revision: 3, modelAvailable: true,
  question: null, humanAnswers: [], exchanges: [], decision: null, steps: [] })
const wrappers: ReturnType<typeof mount>[] = []
const review = (rejected = false) => ({ subjectId: 'graph-1', subjectType: 'planner', reason: 'Recovery authority rejected proposal', reasonCode: 'PLANNER_WAIT', canApprove: !rejected, decisionRejected: rejected, expectedRunUpdatedAt: '2026-10-06T12:00:00Z' })

describe('explicit review interaction', () => {
  it('shows a rejected proposal as blocked and previews new requirements without approving failed work', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: review(true), decision: { action: 'recover', reason: 'Retry failed nodes' }, steps: [{ stepId: 'A', name: '提取事实', status: 'failed' }] })
    vi.mocked(agentosApi.previewCopilotAction).mockResolvedValue({ operationId: 'proposal', user: '恢复', assistant: '待确认', createdAt: '2026-10-06T12:00:00Z', observedRevision: 3 })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3) })
    expect(w.find('.empty-state').exists()).toBe(false)
    expect(w.get('.review-card').text()).toContain('任务暂停，未能自动恢复')
    expect(w.get('.review-card').text()).toContain('提取事实')
    expect(w.get('.review-card').text()).not.toContain('确认条件已满足')
    await w.get('[aria-label="审核意见"]').setValue('修正失败节点后重新规划')
    const button = w.findAll('.review-actions button').find(b => b.text() === '预览调整方案')!
    await button.trigger('click'); await flushPromises()
    expect(agentosApi.previewCopilotAction).toHaveBeenCalledWith('run-1', 'user_input', '修正失败节点后重新规划', expect.any(String), 'task_collaboration', undefined)
    expect(agentosApi.applyWorkflowReview).not.toHaveBeenCalled()
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
  })
  it('submits the persisted review subject and revision, then shows a receipt after the card disappears', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: review() })
    vi.mocked(agentosApi.applyWorkflowReview).mockResolvedValue({} as any)
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canReview: true }) })
    await w.get('[aria-label="审核意见"]').setValue('条件已满足')
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(state())
    await w.get('.review-actions button').trigger('click'); await flushPromises()
    expect(agentosApi.applyWorkflowReview).toHaveBeenCalledWith('run-1', { stepId: 'graph-1', decision: 'approved', comment: '条件已满足', operationId: expect.any(String), expectedRunUpdatedAt: '2026-10-06T12:00:00Z' })
    expect(w.find('.review-card').exists()).toBe(false)
    expect(w.get('.wait-note[role="status"]').text()).toContain('审核已提交')
  })
})
async function panel(props = {}) {
  const wrapper = mount(AcgCopilotPanel, { props: { runId: 'run-1', missionId: 'mission-1',
    actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'running', 3), ...props }, global: { stubs: { ElIcon: { template: '<span><slot /></span>' } } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => { vi.clearAllMocks(); clearCopilotSession('run-1'); clearCopilotSession('run-2'); vi.mocked(agentosApi.getCopilot).mockResolvedValue(state()); vi.mocked(agentosApi.setCopilotPermission).mockImplementation(async (_, permission) => ({ missionId: 'mission-1', taskPermission: permission })); vi.mocked(agentosApi.listRunResourceCalls).mockResolvedValue({ runId: 'run-1', items: [], total: 0 }) })
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.useRealTimers() })
const readyState = (): CopilotState => ({ ...state(), status: 'planning', initialPlan: {
  planVersion: 1, commitId: 'commit', commitmentRevision: 1, objective: '检查加载问题', constraints: [], expectedArtifacts: [], tasks: [],
} })
const readyProps = () => ({
  runtimeObservation: { runId: 'run-1', traces: [], run: { runId: 'run-1', missionId: 'mission-1', status: 'planning', runtimeRevision: 3,
    formalControl: { status: 'PLANNING_ACCEPTED', commitId: 'commit', commitmentRevision: 1 } } },
  actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'planning', 3, { canExecuteFormalAction: true, formalActions: ['materialize'] }),
})

describe('Copilot formal action availability during refresh', () => {
  it.each([false, true])('validates the first snapshot before allowing formal operations (cached: %s)', async cached => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    if (cached) {
      const previous = await panel(readyProps())
      previous.unmount(); wrappers.splice(wrappers.indexOf(previous), 1)
    }
    let finish!: (next: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const w = await panel(readyProps())
    expect(w.getComponent(FormalExecutionControls).get('.formal-control__primary').attributes('disabled')).toBeDefined()
    finish(readyState()); await flushPromises()
    expect(w.getComponent(FormalExecutionControls).get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    expect(agentosApi.submitFormalControl).not.toHaveBeenCalled()
  })

  it('keeps a validated formal action available while its conversation snapshot refreshes', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel(readyProps())
    const controls = w.getComponent(FormalExecutionControls)
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    let finish!: (next: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    controls.vm.$emit('refresh'); await nextTick()
    expect(controls.props('readonly')).toBe(false)
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    expect(w.text()).not.toContain('当前视图仅供查看')
    finish(readyState()); await flushPromises()
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    expect(agentosApi.submitFormalControl).not.toHaveBeenCalled()
  })

  it('preserves a pending formal command and its receipt when an overlapping refresh completes', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel(readyProps())
    const controls = w.getComponent(FormalExecutionControls)
    let acknowledge!: (receipt: any) => void
    vi.mocked(agentosApi.submitFormalControl).mockImplementationOnce(() => new Promise(resolve => { acknowledge = resolve }))
    await controls.get('.formal-control__primary').trigger('click')
    expect(agentosApi.submitFormalControl).toHaveBeenCalledTimes(1)
    controls.vm.$emit('refresh'); await flushPromises()
    expect(controls.get('.formal-control__primary').text()).toBe('正在提交…')
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeDefined()
    await controls.get('.formal-control__primary').trigger('click')
    expect(agentosApi.submitFormalControl).toHaveBeenCalledTimes(1)
    const command = vi.mocked(agentosApi.submitFormalControl).mock.calls[0][3]
    acknowledge({ operationId: command.operationId, status: 'MATERIALIZED_INACTIVE' }); await flushPromises()
    expect(controls.emitted('succeeded')).toHaveLength(1)
  })

  it.each(['response', 'error'])('ignores an older refresh %s after a newer snapshot has arrived', async olderResult => {
    const w = await panel()
    let resolveOlder!: (next: CopilotState) => void, rejectOlder!: (error: unknown) => void, resolveNewer!: (next: CopilotState) => void
    vi.mocked(agentosApi.getCopilot)
      .mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOlder = resolve; rejectOlder = reject }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveNewer = resolve }))
    const older = (w.vm as any).refresh()
    const newer = (w.vm as any).refresh()
    resolveNewer({ ...state(), taskPermission: 'task_collaboration', exchanges: [
      { operationId: 'latest', user: '', assistant: '较新的状态说明', observedRevision: 3, createdAt: '2026-11-14T10:00:02Z' },
    ] }); await newer; await flushPromises()
    if (olderResult === 'response') resolveOlder({ ...state(), taskPermission: 'read_only' })
    else rejectOlder({ response: { status: 403 } })
    await older; await flushPromises()
    expect(w.get('.message-content').text()).toBe('较新的状态说明')
    expect((w.vm as any).permission).toBe('task_collaboration')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it.each([401, 403, 404])('disables controls when the current refresh rejects access (%s)', async status => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel(readyProps())
    vi.mocked(agentosApi.getCopilot).mockRejectedValueOnce({ response: { status } })
    await (w.vm as any).refresh(); await flushPromises()
    expect(w.getComponent(FormalExecutionControls).props('readonly')).toBe(true)
    expect(w.getComponent(FormalExecutionControls).get('.formal-control__primary').attributes('disabled')).toBeDefined()
    expect(agentosApi.submitFormalControl).not.toHaveBeenCalled()
  })
})

describe('task Copilot', () => {
  it('shows planning progress instead of the empty conversation guide during initial planning', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'planning' })
    const w = await panel({ runStatus: 'planning' })
    expect(w.find('.run-timeline__planning').exists()).toBe(true)
    expect(w.find('.empty-watermark').exists()).toBe(false)
    expect(w.text()).not.toContain('一起推进这项任务')
  })
  it('keeps a failed planning run informative when only its durable observations remain', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'failed' })
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [{ eventId: 'planning-failed', runId: 'run-1', eventType: 'task_status_changed',
      payload: { planningProgress: true, kind: 'failed', stage: 'repair', errorCode: 'TASK_PLAN_CONTRACT_FAILED' } }] } })
    expect(w.get('.run-timeline__planning').text()).toContain('本次规划未完成')
    expect(w.find('.empty-watermark').exists()).toBe(false)
  })
  it('puts frozen planning explanations in the conversation and keeps the composer available', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), initialPlan: {
      planVersion: 1, commitId: 'commit', commitmentRevision: 1, objective: '分析故障恢复', constraints: ['不修改代码'], expectedArtifacts: ['方案报告'],
      tasks: [{ key: 'T1', title: '核对事实', objective: '确认输入', rationale: '先建立共同事实依据', acceptanceCriteria: ['标明来源'], sourceRefs: [] }] } })
    const w = await panel()
    expect(w.get('.run-timeline__plan').text()).toContain('先建立共同事实依据')
    expect(w.find('.empty-state').exists()).toBe(false)
    expect(w.find('form textarea').exists()).toBe(true)
  })
  it('interleaves progress with distinct user and assistant messages and keeps chat visible when collapsed', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'failed', exchanges: [
      { operationId: 'before', user: '请检查加载问题', assistant: '开始检查', observedRevision: 3, createdAt: '2026-11-14T10:00:01Z' },
      { operationId: 'after', user: '说明下一步', assistant: '等待你确认', observedRevision: 3, createdAt: '2026-11-14T10:00:03Z' },
    ] })
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [
      { eventId: 'progress', runId: 'run-1', eventType: 'task_status_changed', timestamp: '2026-11-14T10:00:02Z', payload: { planningProgress: true, kind: 'stage_completed', stage: 'decompose' } },
    ] } })
    const rows = Array.from(w.get('.run-timeline').element.children).filter(el => el.tagName === 'ARTICLE').map(el => el.textContent)
    expect(rows).toEqual(['请检查加载问题', '开始检查', '已生成任务步骤与规划依据，后续还需校验是否满足任务约束。', '说明下一步', '等待你确认'])
    await w.get('.run-timeline__history-toggle').trigger('click')
    expect(w.get('.run-timeline__progress').isVisible()).toBe(false)
    expect(w.findAll('.message').every(message => message.isVisible())).toBe(true)
    expect(w.findAll('.message.is-user')).toHaveLength(2)
    expect(w.findAll('.message.is-assistant')).toHaveLength(2)
  })
  it('keeps formal approvals separate from the chat-only conversation preference', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), taskPermission: 'read_only' })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'running', 3, { canResolveToolApproval: true }) })
    const approvals = w.getComponent(FormalToolApprovals)
    expect(approvals.props('active')).toBe(true)
    expect(approvals.props('readonly')).toBe(false)
    await w.setProps({ readonly: true })
    expect(approvals.exists()).toBe(true)
    expect(approvals.props('readonly')).toBe(true)
  })
  it('cannot apply another Run proposal or replace its expected revision with the selected Run capability', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'failed' })
    const wrapper = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'failed', 3) })
    const action = { kind: 'rerun', stepId: null, expectedRevision: 3, executeStepIds: [], reusedStepIds: [], content: '' } as const
    await (wrapper.vm as any).confirmAction('proposal', action, 'run-2')
    await (wrapper.vm as any).confirmAction('proposal', { ...action, expectedRevision: 2 }, 'run-1')
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
  })
  it('pauses cached-view polling and resumes one loop while retaining its unsent draft', async () => {
    vi.useFakeTimers()
    const visible = ref(true)
    const host = defineComponent({ setup: () => () => h(KeepAlive, null, { default: () => visible.value ? h(AcgCopilotPanel, { runId: 'run-1' }) : null }) })
    const w = mount(host, { global: { stubs: { ElIcon: true } } }); wrappers.push(w)
    await flushPromises()
    await w.get('textarea').setValue('unsent Copilot draft')
    const before = vi.mocked(agentosApi.getCopilot).mock.calls.length
    visible.value = false; await nextTick()
    await vi.advanceTimersByTimeAsync(20000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before)
    visible.value = true; await nextTick(); await flushPromises()
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('unsent Copilot draft')
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 1)
    await vi.advanceTimersByTimeAsync(3000); await flushPromises()
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 2)
    w.unmount(); wrappers.splice(wrappers.indexOf(w), 1)
    await vi.advanceTimersByTimeAsync(20000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 2)
  })
  it('owns formal controls and forwards refresh/cancel without issuing commands on mount', async () => {
    const run = {runId:'run-1',missionId:'mission-1',status:'pending',steps:[],formalControl:{status:'PLANNING_ACCEPTED'}}
    const w = await panel({missionId:'mission-1',canCancel:true,runtimeObservation:{runId:'run-1',run,traces:[]}})
    const controls = w.getComponent(FormalExecutionControls)
    expect(w.get('.conversation .formal-control').exists()).toBe(true)
    expect(controls.props()).toMatchObject({embedded:true,conversational:true,runId:'run-1',missionId:'mission-1',readonly:false,canCancel:true})
    controls.vm.$emit('refresh'); await flushPromises()
    expect(w.emitted('refresh-run')).toHaveLength(1)
    controls.vm.$emit('cancel')
    expect(w.emitted('cancel-run')).toHaveLength(1)
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:first-of-type').trigger('click'); await flushPromises()
    expect(controls.props()).toMatchObject({ readonly: false, executionReadonly: true })
    await w.get('.copilot-tabs button:last-child').trigger('click')
    expect(controls.exists()).toBe(true)
    expect(w.get('.conversation').isVisible()).toBe(false)
  })

  it('uses a single review surface and refuses another run observation', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({...state(),status:'waiting_review',review:review()})
    const w = await panel({runtimeObservation:{runId:'run-1',traces:[],run:{runId:'run-1',status:'waiting_review',formalControl:{status:'ACTIVATED'}}}})
    expect(w.getComponent(FormalExecutionControls).props('showReview')).toBe(false)
    expect(w.findAll('.review-card')).toHaveLength(1)
    await w.setProps({runtimeObservation:{runId:'run-2',run:{runId:'run-2',formalControl:{status:'ACTIVATED'}}} as any})
    expect(w.getComponent(FormalExecutionControls).props('run')).toBeNull()
  })
  it('preserves historical proposals as evidence without escalating permission or applying them', async () => {
    const proposal = { sourceRunId: 'run-1', operationId: 'proposal', user: 'rerun', assistant: 'ready', createdAt: '2026-10-06T01:00:00Z', observedRevision: 3,
      action: { kind: 'rerun' as const, stepId: null, expectedRevision: 3, executeStepIds: ['A'], reusedStepIds: [], content: 'rerun', executionEnvironmentChanged: true } }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), runId: 'run-2', missionId: 'mission-1', latestRunId: 'run-2', taskPermission: 'read_only', exchanges: [proposal] })
    const w = await panel({ runId: 'run-2', historical: true })
    expect(w.get('.operation-card button').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('执行环境已更新')
    expect(w.get('[aria-label="选择权限"]').attributes('disabled')).toBeDefined()
    await (w.vm as any).changePermission('task_collaboration')
    expect(agentosApi.setCopilotPermission).not.toHaveBeenCalled()
    await w.get('.operation-card button').trigger('click'); await flushPromises()
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
  })

  it('provides explicit navigation from historical evidence to the current task run', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), latestRunId: 'run-2', taskPermission: 'task_collaboration' })
    const w = await panel({ historical: true })
    await w.get('.readonly-note button').trigger('click')
    expect(w.emitted('select-run')).toEqual([['run-2']])
  })
  it('previews a selected node dependency cut and confirms only through the command endpoint', async () => {
    const snapshot = { ...state(), status: 'completed', steps: [{ stepId: 'A', name: '提取资料', status: 'completed' }, { stepId: 'B', name: '生成报告', status: 'completed' }] }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(snapshot)
    const proposal = { operationId: 'proposal', user: '从生成报告重跑', assistant: '方案已准备', observedRevision: 3, createdAt: '2026-10-05T12:00:00Z', action: { kind: 'rerun_node' as const, stepId: 'B', expectedRevision: 3, executeStepIds: ['B'], reusedStepIds: ['A'], content: '从生成报告重跑' } }
    const receipt = { operationId: 'receipt', user: '', assistant: '已创建新的运行', observedRevision: 0, createdAt: '2026-10-05T12:01:00Z', receipt: { proposalId: 'proposal', runId: 'run-2', kind: 'rerun_node' as const, status: 'queued', executeStepIds: ['B'], reusedStepIds: ['A'] } }
    vi.mocked(agentosApi.previewCopilotAction).mockResolvedValue(proposal)
    vi.mocked(agentosApi.applyCopilotAction).mockResolvedValue(receipt)
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', snapshot.status, 3, { canRerunSuccessor: true }), entry: { entryId: 'step:B', kind: 'task', name: '生成报告', group: 'steps', displayOrder: 2, acgNodeId: 'B' } })
    await w.get('[aria-label="任务操作"]').trigger('click')
    expect((w.get('select').element as HTMLSelectElement).value).toBe('B')
    await w.get('.operation-menu button:nth-of-type(2)').trigger('click'); await flushPromises()
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
    expect(w.get('.operation-card').text()).toContain('复用结果：提取资料')
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...snapshot, exchanges: [proposal, receipt] })
    await w.get('.operation-card button').trigger('click'); await flushPromises()
    expect(agentosApi.applyCopilotAction).toHaveBeenCalledWith('run-1', 'proposal', 3, 'task_collaboration')
    expect(w.get('.operation-card button').text()).toBe('已提交')
    await w.get('.operation-receipt button').trigger('click')
    expect(w.emitted('select-run')).toEqual([['run-2']])
    expect(w.findAll('.message.is-user')).toHaveLength(1)
  })
  it('does not expose executable operations in read-only permission', async () => {
    const w = await panel()
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:first-of-type').trigger('click')
    expect(w.get('[aria-label="任务操作"]').attributes('disabled')).toBeDefined()
    expect(agentosApi.previewCopilotAction).not.toHaveBeenCalled()
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
  })
  it('starts without fabricated messages or a hardcoded model', async () => {
    const w = await panel()
    expect(w.findAll('.message')).toHaveLength(0)
    expect(w.text()).toContain('一起推进这项任务')
    expect(w.text()).not.toContain('GPT-5.6')
    expect(w.text()).not.toContain('演示')
  })
  it('sends a real request, keeps its retry operation, and restores persisted conversation', async () => {
    vi.mocked(agentosApi.streamCopilotMessage).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ operationId: 'ok', user: '解释进展', assistant: '已读取任务', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 })
    const w = await panel()
    await w.get('textarea').setValue('解释进展')
    await w.get('form').trigger('submit'); await flushPromises()
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('解释进展')
    const key = vi.mocked(agentosApi.streamCopilotMessage).mock.calls[0][2]
    const next = state(); next.exchanges = [{ operationId: 'ok', user: '解释进展', assistant: '**已读取任务**', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 }]
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(next)
    await w.get('form').trigger('submit'); await flushPromises()
    expect(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[1][2]).toBe(key)
    expect(w.get('.message-content strong').text()).toBe('已读取任务')
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  })
  it('selects declared thinking effort and displays streamed text before completion without role labels', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), models: [{ id: 'test/model', provider: 'test', model: 'model', reasoningEfforts: ['low', 'high', 'max'] }], defaultModelId: 'test/model' })
    let complete!: (value: any) => void
    vi.mocked(agentosApi.streamCopilotMessage).mockImplementation((_id, _content, _operation, onEvent) => {
      onEvent({ type: 'content', content: '正在**核对**' })
      return new Promise(resolve => { complete = resolve })
    })
    const w = await panel()
    await w.get('[aria-label="选择对话模型"]').trigger('click')
    expect(w.findAll('.effort-options button').map(b => b.text())).toEqual(['关闭', '低', '高', '最高'])
    await w.get('.effort-options button:nth-child(3)').trigger('click')
    await w.get('textarea').setValue('核对进度')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(w.get('.streaming-content').text()).toBe('正在核对')
    expect(w.findAll('.message-meta')).toHaveLength(0)
    expect(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[0][5]?.reasoningEffort).toBe('high')
    complete({ operationId: 'done', user: '核对进度', assistant: '核对完成', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 })
    await flushPromises()
    expect(w.find('.streaming-content').exists()).toBe(false)
  })
  it('restores a warm conversation immediately while validating fresh state before sending', async () => {
    const saved = state(); saved.exchanges = [{ operationId: 'saved', user: '上次的问题', assistant: '已保存的回复', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 }]
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(saved)
    const first = await panel()
    await first.get('textarea').setValue('尚未发送的草稿')
    first.unmount(); wrappers.splice(wrappers.indexOf(first), 1)
    let resolve!: (value: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockReturnValueOnce(new Promise(r => { resolve = r }))
    const second = await panel()
    expect(second.text()).toContain('已保存的回复')
    expect(second.text()).not.toContain('正在读取任务对话')
    expect((second.get('textarea').element as HTMLTextAreaElement).value).toBe('尚未发送的草稿')
    expect(second.get('.send-button').attributes('disabled')).toBeDefined()
    resolve(saved); await flushPromises()
    expect(second.get('.send-button').attributes('disabled')).toBeUndefined()
  })
  it('keeps the same operation when reopening during an unfinished stream', async () => {
    let finish!: (value: any) => void
    vi.mocked(agentosApi.streamCopilotMessage).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ operationId: 'done', user: '继续核对', assistant: '完成', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 })
    const first = await panel()
    await first.get('textarea').setValue('继续核对')
    await first.get('form').trigger('submit'); await flushPromises()
    const operation = vi.mocked(agentosApi.streamCopilotMessage).mock.calls[0][2]
    first.unmount(); wrappers.splice(wrappers.indexOf(first), 1)
    const second = await panel()
    await second.get('form').trigger('submit'); await flushPromises()
    expect(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[1][2]).toBe(operation)
    finish({ operationId: operation, user: '继续核对', assistant: '完成', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 })
    await flushPromises()
  })
  it('answers the exact Planner question with the observed revision', async () => {
    const s = state(); s.status = 'waiting_review'; s.modelAvailable = false
    s.question = { questionId: 'question-1', prompt: '是否包含税费？', choices: ['包含', '不包含'] }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(s)
    vi.mocked(agentosApi.answerPlanner).mockResolvedValue({ ...s, question: null, status: 'retrying' })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canAnswerPlanner: true }) })
    await w.get('.question-choices button').trigger('click')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(agentosApi.answerPlanner).toHaveBeenCalledWith('run-1', 'question-1', '包含', 3, expect.any(String), 'task_collaboration')
    expect(agentosApi.streamCopilotMessage).not.toHaveBeenCalled()
  })
  it('does not send during IME composition and limits historical discussions to read_only', async () => {
    const w = await panel()
    await w.get('textarea').setValue('输入中文')
    await w.get('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    expect(agentosApi.streamCopilotMessage).not.toHaveBeenCalled()
    await w.setProps({ historical: true })
    expect(w.get('.send-button').attributes('disabled')).toBeUndefined()
    expect(w.text()).toContain('可讨论原始证据')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(agentosApi.streamCopilotMessage).toHaveBeenCalledWith('run-1', '输入中文', expect.any(String), expect.any(Function), expect.anything(), expect.objectContaining({ permission: 'read_only' }))
  })
  it('routes the selected model and permission and changes the retry operation when options change', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), models: [{ id: 'provider/model-a', provider: 'provider', model: 'model-a' }], defaultModelId: 'provider/default' })
    vi.mocked(agentosApi.streamCopilotMessage).mockRejectedValue(new Error('offline'))
    const w = await panel()
    await w.get('[aria-label="选择对话模型"]').trigger('click')
    await w.get('.model-menu button:last-of-type').trigger('click')
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:first-of-type').trigger('click')
    await w.get('textarea').setValue('解释进展')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[0][5]).toEqual({ modelId: 'provider/model-a', permission: 'read_only' })
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:last-of-type').trigger('click')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[1][2]).not.toBe(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[0][2])
  })
  it('blocks clarification in read-only mode and allows it after choosing confirmation', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', question: { questionId: 'q', prompt: '请确认', choices: ['确认'] } })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canAnswerPlanner: true }) })
    await w.get('.question-choices button').trigger('click')
    expect(w.get('[aria-label="选择对话模型"]').attributes('disabled')).toBeDefined()
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:first-of-type').trigger('click')
    expect(w.get('.send-button').attributes('disabled')).toBeDefined()
    await w.get('form').trigger('submit'); await flushPromises()
    expect(agentosApi.answerPlanner).not.toHaveBeenCalled()
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:last-of-type').trigger('click')
    expect(w.get('.send-button').attributes('disabled')).toBeUndefined()
  })
  it('ignores a stale state response after changing Runs', async () => {
    let resolve!: (value: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockReturnValueOnce(new Promise(r => { resolve = r })).mockResolvedValueOnce({ ...state(), runId: 'run-2', status: 'completed' })
    const w = await panel()
    await w.setProps({ runId: 'run-2' }); await flushPromises()
    resolve({ ...state(), question: { questionId: 'old', prompt: '旧任务的问题', choices: [] } }); await flushPromises()
    expect(w.text()).not.toContain('旧任务的问题')
    expect(w.text()).toContain('已完成')
  })
  it('renders only recorded trace events and opens their details', async () => {
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [{ eventId: 'e-1', eventType: 'tool_called', observation: 'read_document', timestamp: '2026-10-05T12:00:00Z', stepId: 'step-2', durationMs: 12, payload: { callId: 'call-1' } }] } as any })
    await w.get('.copilot-tabs button:last-child').trigger('click')
    expect(w.text()).toContain('read_document')
    expect(w.text()).toContain('step-2')
    expect(w.get('pre').text()).toContain('call-1')
    await w.get('.trace-toolbar input').setValue('不存在')
    expect(w.findAll('.trace-event')).toHaveLength(0)
  })
})
