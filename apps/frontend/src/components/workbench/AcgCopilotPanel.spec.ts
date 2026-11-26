import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AcgCopilotPanel from './AcgCopilotPanel.vue'
import { agentosApi } from '@/services/api/agentos'
import type { CopilotPermissionReceipt, CopilotState } from '@/services/api/agentos/api/copilot'
import { clearCopilotSession } from './copilotSessionCache'
import FormalExecutionControls from '@/components/workspace/FormalExecutionControls.vue'
import FormalToolApprovals from '@/components/workspace/FormalToolApprovals.vue'
import { capabilitiesFixture } from '@/test/fixtures/runCapabilities'
import { renderMarkdown } from '@/utils/markdown'
import { agentosRequest } from '@/services/api/agentos/client'

vi.mock('@/services/api/agentos', () => ({ agentosApi: { getCopilot: vi.fn(), getAgentPool: vi.fn(), setCopilotPermission: vi.fn(), streamCopilotMessage: vi.fn(), answerPlanner: vi.fn(), listRunResourceCalls: vi.fn(), previewCopilotAction: vi.fn(), applyCopilotAction: vi.fn(), applyWorkflowReview: vi.fn(), submitFormalControl: vi.fn() } }))
vi.mock('@/services/api/agentos/client', () => ({ agentosRequest: { get: vi.fn(async () => ({ data: { items: [] } })), post: vi.fn() } }))
vi.mock('@/workbench/runtime/runtimeEvents', () => ({ acquireRunRuntimeStore: vi.fn(() => null), releaseRunRuntimeStore: vi.fn() }))
vi.mock('@/utils/markdown', async importOriginal => {
  const original = await importOriginal<typeof import('@/utils/markdown')>()
  return { ...original, renderMarkdown: vi.fn(original.renderMarkdown) }
})
const state = (): CopilotState => ({ runId: 'run-1', status: 'running', revision: 3, modelAvailable: true,
  approvalMode: 'ask', policyRevision: 0,
  question: null, humanAnswers: [], exchanges: [], decision: null, steps: [] })
const wrappers: ReturnType<typeof mount>[] = []
const review = (rejected = false) => ({ subjectId: 'graph-1', subjectType: 'planner', reason: 'Recovery authority rejected proposal', reasonCode: 'PLANNER_WAIT', canApprove: !rejected, decisionRejected: rejected, expectedRunUpdatedAt: '2026-10-06T12:00:00Z' })

describe('new tasks in the working Copilot', () => {
  it('creates through the same composer without calling a Run-only discussion endpoint', async () => {
    const createTask = vi.fn().mockResolvedValue(undefined)
    const w = await panel({ runId: null, createTask })
    const input = w.get('textarea[aria-label="任务对话输入"]')
    expect(input.attributes('disabled')).toBeUndefined()
    expect(w.find('.readonly-note').exists()).toBe(false)
    await input.setValue('检查工作区并整理结果')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(createTask).not.toHaveBeenCalled()
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(createTask).toHaveBeenCalledOnce()
    expect(createTask).toHaveBeenCalledWith('检查工作区并整理结果')
    expect(agentosApi.streamCopilotMessage).not.toHaveBeenCalled()
  })

  it('keeps the initial message on failure and prevents duplicate creation while pending', async () => {
    let reject!: (cause: Error) => void
    const createTask = vi.fn(() => new Promise<void>((_, fail) => { reject = fail }))
    const w = await panel({ runId: null, createTask, initialDraft: '需要恢复的目标' })
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('需要恢复的目标')
    await w.get('form').trigger('submit')
    await w.get('form').trigger('submit')
    expect(createTask).toHaveBeenCalledOnce()
    reject(new Error('lost response'))
    await flushPromises()
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('需要恢复的目标')
    expect(w.get('.error-note').text()).toContain('lost response')
    await w.setProps({ creationDisabled: true })
    expect(w.get('.send-button').attributes('disabled')).toBeDefined()
  })
})

describe('explicit review interaction', () => {
  it('projects an equal-revision durable review state above a stale Copilot running state', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), revision: 3, status: 'running' })
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [], run: {
      runId: 'run-1', missionId: 'mission-1', status: 'waiting_review', runtimeRevision: 3,
    } } as any })
    expect(w.get('.context-strip').text()).toContain('已暂停')
    expect(w.get('.context-strip').text()).not.toContain('执行中')
  })
  it('projects an unversioned durable review state above a stale Copilot running state', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'running' })
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [], run: {
      runId: 'run-1', missionId: 'mission-1', status: 'waiting_review',
    } } as any })
    expect(w.get('.context-strip').text()).toContain('已暂停')
    expect(w.get('.context-strip').text()).not.toContain('执行中')
  })
  it('uses the observation status when the durable Run payload is temporarily unavailable', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'running' })
    const w = await panel({ runtimeObservation: { runId: 'run-1', runStatus: 'waiting_review', traces: [] } as any })
    expect(w.get('.context-strip').text()).toContain('已暂停')
    expect(w.get('.context-strip').text()).not.toContain('执行中')
  })
  it('keeps a newer paused decision above an older handoff observation', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), revision: 8, status: 'waiting_review',
      review: { ...review(true), kind: 'planner_rejected' } })
    const run = { runId: 'run-1', missionId: 'mission-1', status: 'retrying', runtimeRevision: 7,
      steps: [], lifecyclePhase: 'recovery', lifecycleMessage: 'Graph activated; awaiting verified execution handoff.' }
    const w = await panel({ runtimeObservation: { runId: 'run-1', run, traces: [] } })
    expect(w.get('.context-strip').text()).toContain('已暂停')
    expect(w.get('.context-strip').text()).not.toContain('awaiting')
    await w.setProps({ runtimeObservation: { runId: 'run-1', run: { ...run, status: 'running', runtimeRevision: 9,
      formalControl: { status: 'ACTIVATED', permitStatus: 'ISSUED' } }, traces: [] } as any })
    expect(w.get('.context-strip').text()).toContain('执行中')
    expect(w.get('.context-strip').text()).not.toContain('awaiting')
  })
  it('uses the current formal recovery message during cleanup and clears it for resumed execution', async () => {
    const message = '节点执行失败，正在停止并行执行并等待清理'
    const run = { runId: 'run-1', missionId: 'mission-1', status: 'running', steps: [],
      lifecyclePhase: 'recovery', lifecycleMessage: message }
    const w = await panel({ runtimeObservation: { runId: 'run-1', run, traces: [] } })
    expect(w.get('.context-strip').text()).toContain(message)
    await w.setProps({ runtimeObservation: { runId: 'run-1', run: { ...run, lifecyclePhase: 'executing' }, traces: [] } as any })
    expect(w.get('.context-strip').text()).toContain('执行中')
    expect(w.get('.context-strip').text()).not.toContain(message)
    await w.setProps({ runtimeObservation: { runId: 'another-run', run, traces: [] } as any })
    expect(w.get('.context-strip').text()).not.toContain(message)
  })
  it('shows a durable graph transition rejection with details and without an approval action', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'retrying', planningProgress: {
      kind: 'blocked', status: 'blocked', message: '自动修订暂时停止，已完成结果已保留',
      observationId: 'transition-observation', errorCode: 'GRAPH_TRANSITION_REJECTED', reason: 'source fingerprint differs', errorType: 'TransitionRejected', canApprove: false
    } })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'retrying', 3, { canReview: true }) })
    expect(w.get('.planning-progress--blocked').text()).toContain('source fingerprint differs')
    expect(w.get('.context-strip').text()).toContain('图交接受阻')
    expect(w.getComponent(FormalExecutionControls).props('showReview')).toBe(false)
    expect(w.find('.planning-progress .is-loading').exists()).toBe(false)
    expect(w.find('.review-card').exists()).toBe(false)
  })
  it('shows active automatic correction as progress without approval or a review form', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'retrying', planningProgress: {
      kind: 'repairing', status: 'retrying', message: '正在根据审查反馈自动修正计划',
      observationId: 'denied-observation', errorCode: 'INVALID_PROPOSAL',
    } })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'retrying', 3, { canReview: true }) })
    expect(w.get('.planning-progress[role="status"]').text()).toBe('正在根据审查反馈自动修正计划')
    expect(w.get('.context-strip').text()).toContain('自动修正中')
    expect(w.find('.review-card').exists()).toBe(false)
    expect(w.find('[aria-label="审核意见"]').exists()).toBe(false)
    expect(w.find('.attention-dot').exists()).toBe(false)
    expect(w.getComponent(FormalExecutionControls).props('showReview')).toBe(false)
    expect(w.text()).not.toContain('确认条件已满足')
    expect(agentosApi.applyWorkflowReview).not.toHaveBeenCalled()
  })
  it('shows automatic revision as internal work without manual barrier confirmation', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: {
      ...review(), kind: 'workspace_revision_pending', canApprove: false,
      reason: 'Workspace review revision queued; settle the evidence barrier before formal graph activation',
      displayReason: '系统正在处理审查计划的自动修订，完成正式校验后会继续执行。',
    } })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canReview: true }) })
    expect(w.get('.review-card strong').text()).toBe('正在自动修订审查计划')
    expect(w.get('.context-strip').text()).toContain('自动修订中')
    expect(w.get('.review-card').text()).not.toContain('确认条件已满足')
    expect(w.get('.review-card').text()).not.toContain('预览调整方案')
    expect(w.find('[aria-label="审核意见"]').exists()).toBe(false)
    expect(w.find('.attention-dot').exists()).toBe(false)
    expect(agentosApi.applyWorkflowReview).not.toHaveBeenCalled()
  })
  it('shows the true revision rejection and failed step even if a stale approve flag is present', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: {
      ...review(), kind: 'workspace_revision_blocked', canApprove: true, decisionRejected: false,
      reasonCode: 'WORKSPACE_REVIEW_REVISION_BLOCKED', errorCode: 'INVALID_PROPOSAL', errorType: '_TransitionRejected',
      reason: 'Workspace review graph transition rejected: INVALID_PROPOSAL: started or settled work cannot be changed',
      displayReason: '修订方案试图更改已开始或已有最终结果的步骤，正式校验已拒绝该方案。',
    }, decision: { action: 'wait', reason: 'Workspace review revision queued; settle the evidence barrier before formal graph activation' },
    steps: [{ stepId: 'S2', name: '核对完整代码证据', status: 'failed' }] })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canReview: true }) })
    expect(w.get('.review-card strong').text()).toBe('审查计划修订受阻')
    expect(w.get('.review-card > p').text()).toContain('已开始或已有最终结果的步骤')
    expect(w.get('.review-card').text()).toContain('核对完整代码证据 · 执行失败')
    expect(w.get('.review-card details').text()).toContain('INVALID_PROPOSAL')
    expect(w.get('.review-card').text()).not.toContain('确认条件已满足')
    expect(w.get('.review-card small').text()).toContain('仍须通过正式校验')
    expect(agentosApi.applyWorkflowReview).not.toHaveBeenCalled()
    await w.findAll('.review-actions button').find(button => button.text() === '查看失败详情')!.trigger('click')
    expect(w.get('.trajectory-view').exists()).toBe(true)
  })
  it('keeps external waits distinct and offers confirmation only for an approvable review', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: {
      ...review(), kind: 'planner_wait', reason: '等待补充外部文件',
    } })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canReview: true }) })
    expect(w.get('.review-card strong').text()).toBe('等待外部条件确认')
    expect(w.get('.review-card').text()).toContain('等待补充外部文件')
    expect(w.findAll('.review-actions button').find(button => button.text() === '确认条件已满足')!.attributes('disabled')).toBeUndefined()
  })
  it('replans a technical Planner failure through the existing persisted review subject', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: {
      ...review(), kind: 'planner_error', reasonCode: 'PLANNER_UNAVAILABLE',
      reason: 'Runtime Planner unavailable: ValidationError', errorCode: 'PLANNER_DECISION_NO_PROGRESS', errorType: 'ValidationError',
      validationFailures: [{ stage: 'decompose', code: 'unknown_task_reference', fieldPath: ['relations', 3, 'sourceKey'] }],
    } })
    vi.mocked(agentosApi.applyWorkflowReview).mockResolvedValue({} as any)
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, { canReview: true }) })
    expect(w.get('.review-card strong').text()).toBe('规划处理失败')
    expect(w.get('.review-card > p').text()).toBe('系统未能生成有效的下一步决策，已有结果已保留。可以重新规划。')
    expect(w.get('.review-card').text()).not.toContain('确认条件已满足')
    expect(w.get('.review-card details summary').text()).toBe('查看技术详情')
    expect(w.get('.review-card details').text()).toContain('错误代码：PLANNER_DECISION_NO_PROGRESS')
    expect(w.get('.review-card details li').text()).toContain('relations[3].sourceKey · 引用了候选计划中未声明的任务')
    const replan = w.findAll('.review-actions button').find(button => button.text() === '重新规划')!
    expect(replan.attributes('disabled')).toBeUndefined()
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(state())
    await replan.trigger('click'); await flushPromises()
    expect(agentosApi.applyWorkflowReview).toHaveBeenCalledWith('run-1', {
      stepId: 'graph-1', decision: 'approved', comment: '', operationId: expect.any(String), expectedRunUpdatedAt: '2026-10-06T12:00:00Z',
    })
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
    expect(w.get('.wait-note[role="status"]').text()).toContain('重新规划已提交')
  })
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
beforeEach(() => { vi.clearAllMocks(); clearCopilotSession('run-1'); clearCopilotSession('run-2'); vi.mocked(agentosApi.getCopilot).mockResolvedValue(state()); vi.mocked(agentosApi.setCopilotPermission).mockImplementation(async (_, permission, change) => ({ missionId: 'mission-1', taskPermission: permission, approvalMode: change?.approvalMode ?? 'ask', policyRevision: (change?.expectedPolicyRevision ?? 0) + 1, autoApprovedCount: 0 })); vi.mocked(agentosApi.listRunResourceCalls).mockResolvedValue({ runId: 'run-1', items: [], total: 0 }) })
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.useRealTimers() })
describe('task automatic approval mode', () => {
  it('offers local recovery on a failed Planner barrier without asking to approve its conditions', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'waiting_review', review: review(),
      steps: [{ stepId: 'reviewer', name: 'Review', status: 'failed' }] })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'waiting_review', 3, {
      canRecoverCurrentRun: true, retryStepId: 'reviewer',
    }) })
    expect(w.text()).not.toContain('确认条件已满足')
    expect(w.get('[aria-label="任务操作"]').attributes('disabled')).toBeUndefined()
    expect(agentosApi.applyWorkflowReview).not.toHaveBeenCalled()
  })
  it('can enable a task policy on the latest failed Run without starting recovery', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'failed' })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'failed', 3) })
    expect(w.get('[aria-label="选择权限"]').attributes('disabled')).toBeUndefined()
    await (w.vm as any).changePermission('task_collaboration', 'full')
    expect(agentosApi.setCopilotPermission).toHaveBeenCalledWith('run-1', 'task_collaboration',
      expect.objectContaining({ approvalMode: 'full' }))
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
  })
  const receipt = (overrides: Partial<CopilotPermissionReceipt> = {}): CopilotPermissionReceipt => ({
    missionId: 'mission-1', taskPermission: 'task_collaboration', approvalMode: 'full', policyRevision: 5, autoApprovedCount: 2, ...overrides,
  })
  it('shows the persisted effective mode without changing collaboration actions', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), taskPermission: 'task_collaboration', approvalMode: 'full', policyRevision: 4 })
    const w = await panel()
    expect(w.get('[aria-label="选择权限"]').text()).toBe('自动审批')
    expect(w.getComponent(FormalExecutionControls).props('executionReadonly')).toBe(false)
    await w.get('[aria-label="选择权限"]').trigger('click')
    expect(w.findAll('[role="menuitemradio"]').map(button => button.text())).toEqual([
      '仅对话查看状态、解释问题和提供建议；不暂停正在执行的任务',
      '按需确认继续协作，文件修改和命令执行按现有规则询问',
      '自动审批自动批准文件修改与命令执行，跨图版本和断点恢复持续有效，直到关闭',
    ])
    expect(w.get('[aria-checked="true"]').text()).toContain('自动审批')
    expect(agentosApi.setCopilotPermission).not.toHaveBeenCalled()
  })
  it('waits for the server receipt and compares the independent policy revision', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), policyRevision: 4 })
    let finish!: (value: CopilotPermissionReceipt) => void
    vi.mocked(agentosApi.setCopilotPermission).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const w = await panel()
    await w.get('[aria-label="选择权限"]').trigger('click')
    await w.get('.permission-menu button:last-of-type').trigger('click')
    expect(agentosApi.setCopilotPermission).toHaveBeenCalledWith('run-1', 'task_collaboration', {
      approvalMode: 'full', expectedPolicyRevision: 4, operationId: expect.any(String),
    })
    expect(w.get('[aria-label="选择权限"]').text()).toBe('正在设置…')
    expect((w.vm as any).approvalMode).toBe('ask')
    finish(receipt()); await flushPromises()
    expect(w.get('[aria-label="选择权限"]').text()).toBe('自动审批')
    expect(w.get('.permission-receipt').text()).toBe('已开启自动审批，已处理 2 项待审批操作')
    expect(agentosRequest.post).not.toHaveBeenCalled()
  })
  it('keeps the previous mode on network failure and retries the identical operation body', async () => {
    const w = await panel()
    vi.mocked(agentosApi.setCopilotPermission).mockRejectedValueOnce(new Error('连接中断'))
    await (w.vm as any).changePermission('task_collaboration', 'full')
    expect(w.get('[aria-label="选择权限"]').text()).toBe('按需确认')
    expect(w.get('[role="alert"]').text()).toContain('连接中断')
    const first = vi.mocked(agentosApi.setCopilotPermission).mock.calls[0]
    // A reconciliation may observe the committed policy before its lost receipt is retried.
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), approvalMode: 'full', policyRevision: 1 })
    await (w.vm as any).refresh(true)
    await (w.vm as any).changePermission('task_collaboration', 'full')
    expect(vi.mocked(agentosApi.setCopilotPermission).mock.calls[1]).toEqual(first)
    await (w.vm as any).changePermission('task_collaboration', 'ask')
    const third = vi.mocked(agentosApi.setCopilotPermission).mock.calls[2]
    expect(third[2]).toMatchObject({ approvalMode: 'ask', expectedPolicyRevision: 1 })
    expect(third[2]!.operationId).not.toBe(first[2]!.operationId)
    expect(w.get('[aria-label="选择权限"]').text()).toBe('按需确认')
    expect(w.get('.permission-receipt').text()).toBe('后续操作将按需确认')
  })
  it('does not let an older GET roll back an acknowledged policy', async () => {
    const w = await panel()
    let finish!: (value: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const reading = (w.vm as any).refresh(true)
    await (w.vm as any).changePermission('task_collaboration', 'full')
    finish({ ...state(), revision: 99 }); await reading
    expect((w.vm as any).state.revision).toBe(99)
    expect((w.vm as any).state.policyRevision).toBe(1)
    expect(w.get('[aria-label="选择权限"]').text()).toBe('自动审批')
  })
  it('does not replace a newer server policy with a delayed permission receipt', async () => {
    const w = await panel()
    let finish!: (value: CopilotPermissionReceipt) => void
    vi.mocked(agentosApi.setCopilotPermission).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const setting = (w.vm as any).changePermission('task_collaboration', 'full')
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), approvalMode: 'ask', policyRevision: 6 })
    await (w.vm as any).refresh(true)
    finish(receipt()); await setting
    expect(w.get('[aria-label="选择权限"]').text()).toBe('按需确认')
    expect(w.find('.permission-receipt').exists()).toBe(false)
  })
  it('ignores an old Run receipt after selecting a different Run', async () => {
    const w = await panel()
    let finish!: (value: CopilotPermissionReceipt) => void
    vi.mocked(agentosApi.setCopilotPermission).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const setting = (w.vm as any).changePermission('task_collaboration', 'full')
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), runId: 'run-2' })
    await w.setProps({ runId: 'run-2', actionCapabilities: capabilitiesFixture('run-2', 'mission-1', 'running', 3) }); await flushPromises()
    finish(receipt()); await setting
    expect((w.vm as any).state.runId).toBe('run-2')
    expect(w.get('[aria-label="选择权限"]').text()).toBe('按需确认')
    expect(w.find('.permission-receipt').exists()).toBe(false)
  })
  it('uses the effective ask mode when a stored full policy no longer matches the workspace', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), approvalMode: 'ask', policyRevision: 4,
      approvalPolicy: { missionId: 'mission-1', permission: 'task_collaboration', approvalMode: 'full', policyRevision: 4,
        workspaceScope: { workspaceId: 'old-workspace', grantId: 'old-grant', resourceId: 'old-resource' } },
    })
    const w = await panel()
    expect(w.get('[aria-label="选择权限"]').text()).toBe('按需确认')
  })
  it('supports keyboard selection and restores focus on Escape', async () => {
    const w = await panel()
    await w.get('[aria-label="选择权限"]').trigger('keydown', { key: 'ArrowDown' })
    expect(w.find('.permission-menu').exists()).toBe(true)
    await w.get('.permission-picker').trigger('keydown', { key: 'End' })
    expect(w.findAll('[role="menuitemradio"]')).toHaveLength(3)
    await w.get('.permission-picker').trigger('keydown', { key: 'Escape' })
    expect(w.find('.permission-menu').exists()).toBe(false)
    expect(agentosApi.setCopilotPermission).not.toHaveBeenCalled()
  })
})
const readyState = (): CopilotState => ({ ...state(), status: 'planning', initialPlan: {
  planVersion: 1, commitId: 'commit', commitmentRevision: 1, objective: '检查加载问题', constraints: [], expectedArtifacts: [], tasks: [],
} })
const readyProps = () => ({
  runtimeObservation: { runId: 'run-1', traces: [], run: { runId: 'run-1', missionId: 'mission-1', status: 'planning', runtimeRevision: 3,
    formalControl: { status: 'PLANNING_ACCEPTED', commitId: 'commit', commitmentRevision: 1 } } },
  actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'planning', 3, { canExecuteFormalAction: true, formalActions: ['materialize'] }),
})

describe('Copilot formal action availability during refresh', () => {
  it.each([false, true])('coalesces formal refreshes after the workspace settles (revision changed: %s)', async changed => {
    vi.useFakeTimers()
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel({ ...readyProps(), projectionRevision: 1, workspaceRefreshing: false })
    const controls = w.getComponent(FormalExecutionControls)
    await w.get('form textarea').setValue('Preserve this draft')
    controls.vm.$emit('refresh'); controls.vm.$emit('refresh'); await flushPromises()
    await w.setProps({ workspaceRefreshing: true })
    await vi.advanceTimersByTimeAsync(1000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(1)
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    await w.setProps({ workspaceRefreshing: false, projectionRevision: changed ? 2 : 1 })
    await vi.advanceTimersByTimeAsync(150); await flushPromises()
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(3000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
    expect((w.get('form textarea').element as HTMLTextAreaElement).value).toBe('Preserve this draft')
    expect(agentosApi.submitFormalControl).not.toHaveBeenCalled()
  })

  it('revalidates an explicit refresh after access recovers and clears the previous error', async () => {
    vi.useFakeTimers()
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel(readyProps())
    const controls = w.getComponent(FormalExecutionControls)
    vi.mocked(agentosApi.getCopilot).mockRejectedValueOnce({ response: { status: 403 }, message: 'Access denied' })
    await (w.vm as any).refresh(); await flushPromises()
    expect(controls.props('readonly')).toBe(true)
    expect(w.get('[role="alert"]').text()).toContain('Access denied')
    controls.vm.$emit('refresh'); await vi.advanceTimersByTimeAsync(150); await flushPromises()
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(3)
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(controls.props('readonly')).toBe(false)
    expect(agentosApi.submitFormalControl).not.toHaveBeenCalled()
  })

  it('does not starve conversation reads when workspace refreshes keep arriving', async () => {
    vi.useFakeTimers()
    const w = await panel({ ...readyProps(), projectionRevision: 1, workspaceRefreshing: false })
    w.getComponent(FormalExecutionControls).vm.$emit('refresh')
    for (let revision = 2; revision <= 4; revision++) {
      await w.setProps({ workspaceRefreshing: true })
      await vi.advanceTimersByTimeAsync(200)
      await w.setProps({ workspaceRefreshing: false, projectionRevision: revision })
      await vi.advanceTimersByTimeAsync(1); await flushPromises()
      expect(agentosApi.getCopilot).toHaveBeenCalledTimes(revision)
    }
    await vi.advanceTimersByTimeAsync(3000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(4)
  })

  it('reconciles a formal refresh arriving during an outstanding conversation read', async () => {
    vi.useFakeTimers()
    const w = await panel(readyProps())
    const controls = w.getComponent(FormalExecutionControls)
    let finish!: (value: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const reading = (w.vm as any).refresh()
    controls.vm.$emit('refresh'); await vi.advanceTimersByTimeAsync(1000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
    finish(state()); await reading; await flushPromises()
    await vi.advanceTimersByTimeAsync(150); await flushPromises()
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(3000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(3)
  })

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
    vi.useFakeTimers()
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel(readyProps())
    const controls = w.getComponent(FormalExecutionControls)
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    let finish!: (next: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    controls.vm.$emit('refresh'); await vi.advanceTimersByTimeAsync(150); await nextTick()
    expect(controls.props('readonly')).toBe(false)
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    expect(w.text()).not.toContain('当前视图仅供查看')
    finish(readyState()); await flushPromises()
    expect(controls.get('.formal-control__primary').attributes('disabled')).toBeUndefined()
    expect(agentosApi.submitFormalControl).not.toHaveBeenCalled()
  })

  it('preserves a pending formal command and its receipt when an overlapping refresh completes', async () => {
    vi.useFakeTimers()
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(readyState())
    const w = await panel(readyProps())
    const controls = w.getComponent(FormalExecutionControls)
    let acknowledge!: (receipt: any) => void
    vi.mocked(agentosApi.submitFormalControl).mockImplementationOnce(() => new Promise(resolve => { acknowledge = resolve }))
    await controls.get('.formal-control__primary').trigger('click')
    expect(agentosApi.submitFormalControl).toHaveBeenCalledTimes(1)
    controls.vm.$emit('refresh'); await vi.advanceTimersByTimeAsync(150); await flushPromises()
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
    expect(w.get('.run-timeline__progress').text()).toContain('本次规划未完成')
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
    const rows = Array.from(w.get('.run-timeline').element.querySelectorAll('article.message, article.run-timeline__progress-item'))
      .map(el => el.querySelector('.message-content, .chat-recovery')?.textContent)
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
  it('discovers pending approvals from same-run execution observations when SSE is unavailable', async () => {
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'running', 3, { canResolveToolApproval: true }) })
    const reads = vi.mocked(agentosRequest.get).mock.calls.length
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [{ approvalId: 'pending', operationSummary: 'Inspect workspace' }] } })
    await w.setProps({ runtimeObservation: { runId: 'run-other', traces: [] } as any }); await flushPromises()
    expect(agentosRequest.get).toHaveBeenCalledTimes(reads)
    await w.setProps({ runtimeObservation: { runId: 'run-1', traces: [] } as any }); await flushPromises()
    expect(agentosRequest.get).toHaveBeenCalledTimes(reads + 1)
    expect(w.get('.tool-approvals').text()).toContain('等待你确认')
    expect(w.get('.context-strip').text()).toContain('等待你确认')
    expect(w.getComponent(FormalToolApprovals).props('readonly')).toBe(false)
    vi.mocked(agentosRequest.get).mockResolvedValue({ data: { items: [] } })
    await w.setProps({ runtimeObservation: { runId: 'run-1', traces: [] } as any }); await flushPromises()
    expect(w.find('.tool-approvals').exists()).toBe(false)
    expect(agentosRequest.post).not.toHaveBeenCalled()
  })
  it('cannot apply another Run proposal or replace its expected revision with the selected Run capability', async () => {
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'failed' })
    const wrapper = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'failed', 3) })
    const action = { kind: 'rerun', stepId: null, expectedRevision: 3, executeStepIds: [], reusedStepIds: [], content: '' } as const
    await (wrapper.vm as any).confirmAction('proposal', action, 'run-2')
    await (wrapper.vm as any).confirmAction('proposal', { ...action, expectedRevision: 2 }, 'run-1')
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
  })
  it('refreshes a reactivated view once and retains its draft without periodic reads', async () => {
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
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 1)
    w.unmount(); wrappers.splice(wrappers.indexOf(w), 1)
    await vi.advanceTimersByTimeAsync(20000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 1)
  })
  it('coalesces Mission revisions without opening another stream or disabling valid controls', async () => {
    vi.useFakeTimers()
    const w = await panel({ projectionRevision: 1 })
    const before = vi.mocked(agentosApi.getCopilot).mock.calls.length
    await vi.advanceTimersByTimeAsync(30000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before)
    await w.setProps({ projectionRevision: 2 })
    await w.setProps({ projectionRevision: 4 })
    await vi.advanceTimersByTimeAsync(150); await flushPromises()
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 1)
    expect((w.vm as any).loading).toBe(false)
    await w.setProps({ projectionRevision: 4 })
    await w.setProps({ projectionRevision: 3 })
    await vi.advanceTimersByTimeAsync(3000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(before + 1)
  })
  it('reads the latest revision once more when it changes during an outstanding read', async () => {
    vi.useFakeTimers()
    const w = await panel({ projectionRevision: 1 })
    let finish!: (value: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await w.setProps({ projectionRevision: 2 })
    await vi.advanceTimersByTimeAsync(150)
    await w.setProps({ projectionRevision: 3 })
    await w.setProps({ projectionRevision: 4 })
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
    finish(state()); await flushPromises()
    await vi.advanceTimersByTimeAsync(150); await flushPromises()
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(30000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(3)
  })
  it('defers changed revisions during generation and flushes them after the reply finishes', async () => {
    vi.useFakeTimers()
    let complete!: (value: any) => void
    vi.mocked(agentosApi.streamCopilotMessage).mockImplementation(() => new Promise(resolve => { complete = resolve }))
    const w = await panel({ projectionRevision: 1 })
    await w.get('textarea').setValue('检查进度')
    await w.get('form').trigger('submit'); await flushPromises()
    await w.setProps({ projectionRevision: 2 })
    await vi.advanceTimersByTimeAsync(1000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(1)
    complete({ operationId: 'done', user: '检查进度', assistant: 'done', createdAt: '', observedRevision: 3 })
    await flushPromises(); await vi.advanceTimersByTimeAsync(1000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
  })
  it('does not resurrect access-denied state when a later Mission revision arrives', async () => {
    vi.useFakeTimers()
    const w = await panel({ projectionRevision: 1 })
    vi.mocked(agentosApi.getCopilot).mockRejectedValueOnce({ response: { status: 403 } })
    await w.setProps({ projectionRevision: 2 })
    await vi.advanceTimersByTimeAsync(150); await flushPromises()
    await w.setProps({ projectionRevision: 3 })
    await vi.advanceTimersByTimeAsync(1000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
    expect((w.vm as any).state).toBeNull()
  })
  it('retries a temporary invalidation failure within a fixed budget, then stays idle', async () => {
    vi.useFakeTimers()
    const w = await panel({ projectionRevision: 1 })
    vi.mocked(agentosApi.getCopilot).mockRejectedValue({ response: { status: 503 } })
    await w.setProps({ projectionRevision: 2 })
    await vi.advanceTimersByTimeAsync(150)
    await vi.advanceTimersByTimeAsync(3000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(4)
    await vi.advanceTimersByTimeAsync(30000)
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(4)
  })
  it('discards a pending revision and old response when the selected Run changes', async () => {
    vi.useFakeTimers()
    const w = await panel({ projectionRevision: 1 })
    let finishOld!: (value: CopilotState) => void
    vi.mocked(agentosApi.getCopilot).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    await w.setProps({ projectionRevision: 2 })
    await vi.advanceTimersByTimeAsync(150)
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), runId: 'run-2', taskPermission: 'read_only' })
    await w.setProps({ runId: 'run-2', projectionRevision: 3 }); await flushPromises()
    finishOld({ ...state(), taskPermission: 'task_collaboration' }); await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    expect((w.vm as any).state.runId).toBe('run-2')
    expect((w.vm as any).permission).toBe('read_only')
    expect(agentosApi.getCopilot).toHaveBeenCalledTimes(3)
  })
  it('defers invalidation while the document is hidden and reconciles once visible', async () => {
    vi.useFakeTimers()
    const w = await panel({ projectionRevision: 1 })
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    try {
      document.dispatchEvent(new Event('visibilitychange'))
      await w.setProps({ projectionRevision: 2 })
      await vi.advanceTimersByTimeAsync(1000)
      expect(agentosApi.getCopilot).toHaveBeenCalledTimes(1)
      hidden.mockReturnValue(false)
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.advanceTimersByTimeAsync(150); await flushPromises()
      expect(agentosApi.getCopilot).toHaveBeenCalledTimes(2)
    } finally { hidden.mockRestore() }
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
    await w.findAll('.copilot-tabs button')[1].trigger('click')
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
  it('previews and confirms formally offered current Run recovery with precise reuse wording', async () => {
    const snapshot = { ...state(), status: 'failed', steps: [
      { stepId: 'A', name: '提取资料', status: 'completed' }, { stepId: 'B', name: '生成报告', status: 'failed' },
    ] }
    const proposal = { operationId: 'current-proposal', user: '恢复失败任务', assistant: '方案已准备', observedRevision: 3,
      createdAt: '2026-10-05T12:00:00Z', action: { kind: 'recover' as const, retryMode: 'current_run' as const,
        stepId: 'B', expectedRevision: 3, executeStepIds: ['B'], reusedStepIds: ['A'], content: '恢复失败任务' } }
    const receipt = { operationId: 'current-receipt', user: '', assistant: '已继续当前运行', observedRevision: 4,
      createdAt: '2026-10-05T12:01:00Z', receipt: { proposalId: proposal.operationId, runId: 'run-1',
        kind: 'recover' as const, status: 'queued', executeStepIds: ['B'], reusedStepIds: ['A'] } }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue(snapshot)
    vi.mocked(agentosApi.previewCopilotAction).mockResolvedValue(proposal)
    vi.mocked(agentosApi.applyCopilotAction).mockResolvedValue(receipt)
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'failed', 3,
      { canRecoverCurrentRun: true, retryStepId: 'B' }) })
    expect(w.get('[aria-label="任务操作"]').attributes('disabled')).toBeUndefined()
    await w.get('[aria-label="任务操作"]').trigger('click')
    const recover = w.findAll('.operation-menu button').find(button => button.text().includes('恢复失败任务'))!
    expect(recover.attributes('disabled')).toBeUndefined()
    expect(recover.text()).toContain('在当前 Run')
    await recover.trigger('click'); await flushPromises()
    expect(agentosApi.previewCopilotAction).toHaveBeenCalledWith('run-1', 'recover', '恢复失败任务',
      expect.any(String), 'task_collaboration', undefined)
    expect(w.get('.operation-card').text()).toContain('在当前 Run 继续执行')
    expect(w.get('.operation-card').text()).not.toContain('创建新 Run')
    expect(w.get('.operation-card button').attributes('disabled')).toBeUndefined()
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...snapshot, exchanges: [proposal, receipt] })
    await w.get('.operation-card button').trigger('click'); await flushPromises()
    expect(agentosApi.applyCopilotAction).toHaveBeenCalledWith('run-1', proposal.operationId, 3, 'task_collaboration')
    expect(w.find('.operation-receipt button').exists()).toBe(false)
  })
  it.each([undefined, 'successor_run'])('does not confirm a %s recovery proposal with a current Run offer', async retryMode => {
    const action = { kind: 'recover' as const, retryMode: retryMode as 'successor_run' | undefined,
      stepId: 'B', expectedRevision: 3, executeStepIds: ['B'], reusedStepIds: ['A'], content: '恢复' }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), status: 'failed', exchanges: [{
      operationId: 'mismatch', user: '恢复', assistant: '方案', observedRevision: 3, createdAt: '', action,
    }] })
    const w = await panel({ actionCapabilities: capabilitiesFixture('run-1', 'mission-1', 'failed', 3,
      { canRecoverCurrentRun: true, retryStepId: 'B' }) })
    expect(w.get('.operation-card button').attributes('disabled')).toBeDefined()
    await (w.vm as any).confirmAction('mismatch', action, 'run-1')
    expect(agentosApi.applyCopilotAction).not.toHaveBeenCalled()
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
    vi.useFakeTimers()
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
    await vi.advanceTimersByTimeAsync(16)
    expect(w.get('.streaming-content').text()).toBe('正在核对')
    expect(w.findAll('.message-meta')).toHaveLength(0)
    expect(vi.mocked(agentosApi.streamCopilotMessage).mock.calls[0][5]?.reasoningEffort).toBe('high')
    complete({ operationId: 'done', user: '核对进度', assistant: '核对完成', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 })
    await flushPromises()
    expect(w.find('.streaming-content').exists()).toBe(false)
  })
  it('batches preview snapshots, flushes on progress, and keeps completed Markdown stable', async () => {
    vi.useFakeTimers()
    const saved = { operationId: 'old', user: '', assistant: '**已完成的说明**', createdAt: '2026-10-05T12:00:00Z', observedRevision: 3 }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), exchanges: [saved] })
    let receive!: Parameters<typeof agentosApi.streamCopilotMessage>[3]
    let complete!: (value: any) => void
    vi.mocked(agentosApi.streamCopilotMessage).mockImplementation((_id, _content, _operation, onEvent) => {
      receive = onEvent
      return new Promise(resolve => { complete = resolve })
    })
    const w = await panel({ projectionRevision: 1 })
    const oldElement = w.get('.message-content strong').element
    const oldParses = () => vi.mocked(renderMarkdown).mock.calls.filter(([text]) => text === saved.assistant).length
    const before = oldParses()
    await w.get('textarea').setValue('继续')
    await w.get('form').trigger('submit'); await flushPromises()
    receive({ type: 'progress', phase: 'waiting_model' }); await nextTick()
    expect(w.get('.stream-activity').text()).toBe('等待模型响应')
    for (let i = 1; i <= 100; i++) receive({ type: 'content', content: '文'.repeat(i), attemptId: 'a1' })
    await nextTick()
    expect(w.find('.streaming-content').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(16)
    expect(w.get('.streaming-content').text()).toBe('文'.repeat(100))
    receive({ type: 'content', content: '文'.repeat(101), attemptId: 'a1' })
    receive({ type: 'progress', phase: 'validating' }); await nextTick()
    expect(w.get('.streaming-content').text()).toBe('文'.repeat(101))
    expect(w.get('.stream-activity').text()).toBe('正在校验并保存回复')
    const reply = { operationId: 'new', user: '继续', assistant: '已核对', createdAt: '2026-10-05T12:01:00Z', observedRevision: 3,
      responseTimings: { firstContentMs: 1200 }, latencyMs: 3400, providerRequest: 2 }
    vi.mocked(agentosApi.getCopilot).mockResolvedValue({ ...state(), exchanges: [saved, reply] })
    complete(reply); await flushPromises()
    expect(w.get('.response-stats').text()).toBe('首段正文 1.2 秒 · 完成 3.4 秒 · 2 次模型请求')
    expect(w.get('.message-content strong').element).toBe(oldElement)
    expect(oldParses()).toBe(before)
    expect(vi.mocked(renderMarkdown).mock.calls.filter(([text]) => text === '文'.repeat(100))).toHaveLength(1)
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
  it('counts loaded activities by category and merges model projections by trace identity', async () => {
    const usage = { inputTokens: 2, outputTokens: 1, totalTokens: 3, cacheReadTokens: 0, cacheWriteTokens: 0, reasoningTokens: 0 }
    const first = { callId: 'model-trace', model: 'glm-test', usage, latencyMs: 12, outputPolicy: 'default', outputExhausted: false }
    vi.mocked(agentosApi.listRunResourceCalls).mockResolvedValueOnce({ runId: 'run-1', items: [first], total: 2, nextCursor: 'next' })
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [
      { eventId: 'planner', eventType: 'task_status_changed', observation: 'Planner started', payload: { category: 'planner', planningProgress: true } },
      { eventId: 'model-trace', eventType: 'model_called', observation: 'Model invocation metadata projected', payload: { model: 'glm-test' } },
      { eventId: 'tool', eventType: 'tool_called', observation: 'read file', payload: { callId: 'model-trace' } },
      { eventId: 'execution', eventType: 'step_started', observation: 'step started', payload: {} },
    ] } } as any)
    await w.findAll('.copilot-tabs button')[1].trigger('click'); await flushPromises()
    expect(w.findAll('.trace-event')).toHaveLength(4)
    expect(w.get('.trace-toolbar').text()).toContain('已加载 4 条')
    expect(w.get('.trace-lanes').text()).toContain('规划 1')
    expect(w.get('.trace-lanes').text()).toContain('模型 1')
    expect(w.find('.trace-event pre').exists()).toBe(false)
    ;(w.get('.trace-event.lane-model').element as HTMLDetailsElement).open = true
    await w.get('.trace-event.lane-model').trigger('toggle')
    expect(w.get('.trace-event.lane-model pre').text()).toContain('Model invocation metadata projected')
    expect(w.get('.load-more').text()).toContain('加载更多模型调用')
    await w.get('.trace-toolbar input').setValue('规划')
    expect(w.get('.trace-toolbar').text()).toContain('匹配 1 / 已加载 4 条')
    expect(w.findAll('.trace-event')).toHaveLength(1)
    expect(w.get('.trace-lanes').text()).toContain('模型 0')
    await w.get('.trace-toolbar input').setValue('')
    vi.mocked(agentosApi.listRunResourceCalls).mockResolvedValueOnce({ runId: 'run-1', items: [first, { ...first, callId: 'second' }], total: 2 })
    await w.get('.load-more').trigger('click'); await flushPromises()
    expect(w.get('.trace-toolbar').text()).toContain('已加载 5 条')
    expect(w.get('.trace-lanes').text()).toContain('模型 2')
    expect(w.find('.load-more').exists()).toBe(false)
  })
  it('renders only recorded trace events and opens their details', async () => {
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [{ eventId: 'e-1', eventType: 'tool_called', observation: 'read_document', timestamp: '2026-10-05T12:00:00Z', stepId: 'step-2', durationMs: 12, payload: { callId: 'call-1' } }] } as any })
    await w.findAll('.copilot-tabs button')[1].trigger('click')
    expect(w.text()).toContain('read_document')
    expect(w.text()).toContain('step-2')
    expect(w.find('pre').exists()).toBe(false)
    ;(w.get('.trace-event').element as HTMLDetailsElement).open = true
    await w.get('.trace-event').trigger('toggle')
    expect(w.get('pre').text()).toContain('call-1')
    await w.get('.trace-toolbar input').setValue('不存在')
    expect(w.findAll('.trace-event')).toHaveLength(0)
  })
  it('reads activity payloads only while their details are expanded and keeps open evidence current', async () => {
    const serialize = vi.fn(() => ({ evidence: 'first recorded result' }))
    const trace = { eventId: 'evidence', eventType: 'step_completed', observation: 'Recorded evidence', payload: { toJSON: serialize } }
    const observation = { runId: 'run-1', traces: [trace] }
    const w = await panel({ runtimeObservation: observation } as any)
    expect(w.findAll('.copilot-tabs button')[1].text()).toContain('1')
    expect(serialize).not.toHaveBeenCalled()
    await w.findAll('.copilot-tabs button')[1].trigger('click'); await flushPromises()
    await w.get('.trace-toolbar input').setValue('Recorded')
    expect(w.findAll('.trace-event')).toHaveLength(1)
    expect(serialize).not.toHaveBeenCalled()
    const detail = w.get('.trace-event')
    ;(detail.element as HTMLDetailsElement).open = true
    await detail.trigger('toggle')
    expect(w.get('.trace-event pre').text()).toContain('first recorded result')
    expect(serialize).toHaveBeenCalledTimes(1)
    await w.get('textarea').setValue('An unrelated draft')
    expect(serialize).toHaveBeenCalledTimes(1)
    const updated = vi.fn(() => ({ evidence: 'updated recorded result' }))
    await w.setProps({ runtimeObservation: { ...observation, traces: [{ ...trace, payload: { toJSON: updated } }] } } as any)
    expect(w.get('.trace-event pre').text()).toContain('updated recorded result')
    expect(updated).toHaveBeenCalledTimes(1)
    ;(detail.element as HTMLDetailsElement).open = false
    await detail.trigger('toggle')
    await w.setProps({ runtimeObservation: observation } as any)
    expect(w.find('.trace-event pre').exists()).toBe(false)
    expect(serialize).toHaveBeenCalledTimes(1)
  })
  it('keeps each model call associated with its own projections and tools separate', async () => {
    const usage = { inputTokens: 2, outputTokens: 1, totalTokens: 3, cacheReadTokens: 0, cacheWriteTokens: 0, reasoningTokens: 0 }
    const call = { model: 'test-model', usage, latencyMs: 12, outputPolicy: 'default', outputExhausted: false }
    vi.mocked(agentosApi.listRunResourceCalls).mockResolvedValueOnce({ runId: 'run-1', items: [
      { ...call, callId: 'first' }, { ...call, callId: 'second' },
    ], total: 2 })
    const w = await panel({ runtimeObservation: { runId: 'run-1', traces: [
      { eventId: 'first', eventType: 'model_called', observation: 'First invocation', payload: {} },
      { eventId: 'first-output', eventType: 'model_output', payload: { callId: 'first', evidence: 'First output' } },
      { eventId: 'second', eventType: 'model_called', observation: 'Second invocation', payload: {} },
      { eventId: 'separate-tool', eventType: 'tool_called', observation: 'Separate tool', payload: { callId: 'first' } },
    ] } } as any)
    await w.findAll('.copilot-tabs button')[1].trigger('click'); await flushPromises()
    expect(w.get('.trace-toolbar').text()).toContain('已加载 3 条')
    expect(w.findAll('.trace-event.lane-model')).toHaveLength(2)
    expect(w.findAll('.trace-event.lane-tool')).toHaveLength(1)
    const detail = w.findAll('.trace-event.lane-model')[0]
    ;(detail.element as HTMLDetailsElement).open = true
    await detail.trigger('toggle')
    const evidence = JSON.parse(detail.get('pre').text())
    expect(evidence.callId).toBe('first')
    expect(evidence.trace.map((event: { eventId: string }) => event.eventId)).toEqual(['first', 'first-output'])
    expect(detail.text()).toContain('First output')
    expect(detail.text()).not.toContain('Second invocation')
    expect(detail.text()).not.toContain('Separate tool')
  })
})
