import { mount } from '@vue/test-utils'
import { h, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CopilotRunTimeline from './CopilotRunTimeline.vue'
import { acquireRunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import type { CopilotInitialPlan } from '@/services/api/agentos/api/copilot'
import { RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import type { RuntimeTraceObservation } from '@/workbench/runtime/observation'

vi.mock('@/workbench/runtime/runtimeEvents', async original => ({ ...await original<typeof import('@/workbench/runtime/runtimeEvents')>(), acquireRunRuntimeStore: vi.fn(), releaseRunRuntimeStore: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => { vi.mocked(acquireRunRuntimeStore).mockImplementation(runId => runId ? new RunRuntimeStore(runId) : null) })
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks(); vi.useRealTimers() })
const plan: CopilotInitialPlan = { planVersion: 1, commitId: 'commit', commitmentRevision: 1,
  objective: '分析恢复策略', constraints: ['只做分析，不修改代码'], expectedArtifacts: ['报告'],
  tasks: [{ key: 'T1', title: '核对事实', objective: '确认输入', rationale: '为下游建立共同事实依据', acceptanceCriteria: ['标明来源'], sourceRefs: [] }] }
describe('Copilot task timeline', () => {
  it('keeps policy approval evidence inside its tool result without implying execution success', () => {
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running', tools: [{
      executionId: 'command', tool: 'command.run', status: 'failed', stepId: 'node', attemptId: 'attempt',
      createdAt: '2026-11-17T10:00:01Z', resultPreview: 'process exited with code 1',
      approvalDecision: { source: 'policy', policyRevision: 7, actor: { userId: 'operator', tenantId: 'tenant' }, decidedAt: '2026-11-17T10:00:00Z' },
    }] } }); wrappers.push(w)
    expect(w.findAll('.run-timeline__tool')).toHaveLength(1)
    expect(w.get('.run-timeline__auto-approved').text()).toBe('已自动批准')
    expect(w.get('.run-timeline__tools > summary').text()).toContain('已自动批准')
    expect(w.get('.run-timeline__tool .run-timeline__flag').classes()).toContain('is-failed')
    expect(w.get('[aria-label="工具审批记录"]').text()).toContain('任务自动审批策略')
    expect(w.get('[aria-label="工具审批记录"]').text()).toContain('operator · tenant')
    expect(w.get('[aria-label="工具审批记录"]').text()).toContain('策略版本7')
    expect(w.get('.run-timeline__tool-result').text()).toBe('process exited with code 1')
  })
  it('retains persisted approval metadata when a live completion omits it and accepts live decisions', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const decision = { source: 'policy' as const, policyRevision: 2, actor: { userId: 'operator', tenantId: 'tenant' }, decidedAt: '2026-11-17T10:00:00Z' }
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running', tools: [{
      executionId: 'command', tool: 'command.run', status: 'completed', stepId: 'node', attemptId: 'attempt',
      createdAt: '2026-11-17T10:00:01Z', approvalDecision: decision,
    }] } }); wrappers.push(w)
    store.apply({ eventId: 'completed-1', sequence: 1, runId: 'run', nodeId: 'node', attemptId: 'attempt',
      eventType: 'tool.execution_completed', timestamp: '2026-11-17T10:00:01Z', payload: { executionId: 'command', tool: 'command.run', status: 'completed' } })
    store.apply({ eventId: 'completed-2', sequence: 2, runId: 'run', nodeId: 'node', attemptId: 'attempt',
      eventType: 'tool.execution_completed', timestamp: '2026-11-17T10:00:02Z', payload: { executionId: 'command-2', tool: 'command.run', status: 'completed', approvalDecision: decision } })
    await w.vm.$nextTick()
    expect(w.findAll('.run-timeline__auto-approved')).toHaveLength(2)
    expect(w.findAll('[aria-label="工具审批记录"]')).toHaveLength(2)
    expect(w.findAll('.run-timeline__tools')).toHaveLength(1)
    store.dispose()
  })
  it('shows workspace review diagnostics without resetting planning output and respects approval and terminal state', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    const apply = (sequence: number, eventType: string, payload: Record<string, unknown> = {}) => store.apply({
      eventId: `review-${sequence}`, runId: 'run', sequence, eventType,
      timestamp: new Date(sequence * 1000).toISOString(), payload,
    })
    apply(1, 'planner.model.started', { stage: 'outline', callKey: 'outline' })
    apply(2, 'planner.model.reasoning.delta', { delta: '核对需要读取的依据' })
    apply(3, 'planner.model.output.delta', { publicText: '已经收到的规划内容' })
    apply(4, 'planner.model.completed')
    apply(5, 'workspace.review.retry', { stage: 'workspace_review', status: 'retrying', errorCode: 'REVIEW_BUSY' })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__state').text()).toBe('仓库审查正在重试')
    expect(w.get('.run-timeline__review-error').text()).toBe('REVIEW_BUSY')
    expect(w.text()).toContain('核对需要读取的依据')
    expect(w.text()).toContain('已经收到的规划内容')
    apply(6, 'workspace.review.blocked', { errorCode: 'REVIEW_EVIDENCE_MISSING' })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__state').text()).toBe('仓库审查暂时受阻')
    expect(w.get('.run-timeline__review-error').text()).toBe('REVIEW_EVIDENCE_MISSING')
    apply(7, 'workspace.review.resumed', { stage: 'workspace_review', status: 'resumed' })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__state').text()).toBe('正在执行')
    expect(w.find('.run-timeline__review-error').exists()).toBe(false)
    expect(w.text()).toContain('核对需要读取的依据')
    expect(w.text()).toContain('已经收到的规划内容')
    apply(8, 'workspace.review.blocked', { errorCode: 'REVIEW_EVIDENCE_MISSING' })
    await w.vm.$nextTick()
    await w.setProps({ waitingForApproval: true })
    expect(w.get('.run-timeline__state').text()).toBe('等待你确认')
    expect(w.find('.run-timeline__review-error').exists()).toBe(false)
    await w.setProps({ waitingForApproval: false, status: 'completed' })
    expect(w.get('.run-timeline__state').text()).toBe('本次运行已完成')
    expect(w.find('.run-timeline__review-error').exists()).toBe(false)
    expect(w.text()).toContain('已经收到的规划内容')
    store.dispose()
  })
  it('does not let a stale review retry override a completed formal review', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    store.apply({ eventId: 'retry', sequence: 1, runId: 'run', eventType: 'workspace.review.retry', payload: { errorCode: 'REVIEW_BUSY' } })
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running', workspaceReview: {
      schemaVersion: 1, graphVersion: 3, round: 2, status: 'completed', rounds: [],
      gaps: { missingReadCount: 0, missingListingCount: 0, unsupportedEntryCount: 0,
        missingReads: [], missingListings: [], unsupportedEntries: [] },
    } } }); wrappers.push(w)
    expect(w.get('.run-timeline__state').text()).toBe('正在执行')
    expect(w.find('.run-timeline__review-error').exists()).toBe(false)
    store.dispose()
  })
  it('keeps repository review rounds and evidence alongside repeated node tool calls', async () => {
    const workspaceReview = { schemaVersion: 1 as const, round: 2, graphVersion: 3, status: 'reading' as const,
      gaps: { missingReadCount: 105, missingListingCount: 8, unsupportedEntryCount: 0,
        missingReads: ['src/next.py'], missingListings: ['tests'], unsupportedEntries: [] },
      rounds: [{ round: 1, graphVersion: 2, action: 'revise', reason: '补读尚未覆盖的文件',
        stepIds: ['read-1'], addedStepIds: ['read-1'], observationRef: 'observation:1', traceRefs: ['trace:review'] }],
    }
    const tools = ['a.py', 'b.py'].map((target, index) => ({ executionId: `read-${index}`, tool: 'fs.read',
      status: 'completed', stepId: 'read-1', attemptId: 'attempt', createdAt: new Date(index * 1000).toISOString(), target }))
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running', workspaceReview, tools } }); wrappers.push(w)
    expect(w.get('[aria-label="仓库审查进展"]').text()).toContain('第 2 轮')
    expect(w.text()).toContain('文件 105')
    expect(w.text()).toContain('observation:1')
    expect(w.text()).toContain('trace:review')
    expect(w.findAll('.run-timeline__tool-target').map(item => item.text())).toEqual(['a.py', 'b.py'])
    await w.setProps({ workspaceReview: { ...workspaceReview, round: 3, graphVersion: 4, status: 'completed',
      gaps: { ...workspaceReview.gaps, missingReadCount: 0, missingListingCount: 0 } } })
    expect(w.get('[aria-label="仓库审查进展"]').text()).toContain('第 3 轮')
    expect(w.text()).toContain('图 v4')
    expect(w.findAll('.run-timeline__tool-target')).toHaveLength(2)
  })
  it('keeps Agent instance, model turns and tool results in the same work area', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    let sequence = 0
    const apply = (eventType: string, payload: Record<string, unknown>) => store.apply({ eventId: `agent-${++sequence}`, sequence,
      eventType, runId: 'run', nodeId: 'node', attemptId: 'attempt', timestamp: new Date(sequence * 1000).toISOString(), payload })
    apply('node.started', { agentName: '代码分析 Agent', agentRegistration: { agentId: 'analyst', instanceId: 'instance-7', generation: 2 }, nodeTitle: '提取依赖' })
    apply('model.started', { model: 'glm-test', callId: 'call-1' })
    apply('model.reasoning.delta', { delta: '先检查目录。' })
    apply('model.completed', {})
    apply('tool.execution_completed', { tool: 'fs.list', executionId: 'exec-1', status: 'completed', target: 'src', resultPreview: 'main.py' })
    apply('model.started', { model: 'glm-test', callId: 'call-2' })
    await w.vm.$nextTick()
    expect(w.findAll('.agent-work')).toHaveLength(1)
    expect(w.get('.agent-work__heading').text()).toContain('代码分析 Agent')
    expect(w.get('.agent-work__heading').text()).toContain('instance-7')
    expect(w.get('.agent-work').text()).toContain('glm-test')
    expect(w.get('.agent-work').text()).toContain('先检查目录。')
    expect(w.get('.run-timeline__tool-target').text()).toBe('src')
    expect(w.get('.run-timeline__tool-result').text()).toBe('main.py')
    expect(w.findAll('.run-timeline__output')).toHaveLength(2)
    store.dispose()
  })
  it('shows execution reasoning before any answer is returned', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    store.apply({ eventId: 'start', sequence: 1, runId: 'run', nodeId: 'node', eventType: 'model.started' })
    store.apply({ eventId: 'thought', sequence: 2, runId: 'run', nodeId: 'node', eventType: 'model.reasoning.delta', payload: { delta: '先检查输入依据，再核对约束。' } })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__reasoning').text()).toContain('先检查输入依据')
    expect(w.get('[aria-label="执行节点思考过程"]').text()).toContain('先检查输入依据')
    expect(w.get('.run-timeline__reasoning > summary').text()).toContain('思考过程')
    store.apply({ eventId: 'next-thought', sequence: 3, runId: 'run', nodeId: 'node', eventType: 'model.reasoning.delta', payload: { delta: '继续核对依赖关系。' } })
    await w.vm.$nextTick()
    expect(w.get('[aria-label="执行节点思考过程"]').text()).toContain('继续核对依赖关系。')
    expect(w.get('.run-timeline__output-heading').text()).toContain('正在思考')
    expect(w.find('.task-work-summary').exists()).toBe(false)
    store.dispose()
  })
  it('renders the initial plan objective as Markdown rather than preformatted plain text', () => {
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'pending', plan: { ...plan,
      objective: '# # 任务目标\n\n设计**实验室平台**。\n\n- 明确权限\n- 完成验收\n\n<script>alert(1)</script>',
    } } }); wrappers.push(w)
    expect(w.get('.run-timeline__objective h2').text()).toBe('任务目标')
    expect(w.get('.run-timeline__objective strong').text()).toBe('实验室平台')
    expect(w.findAll('.run-timeline__objective li')).toHaveLength(2)
    expect(w.find('.run-timeline__objective script').exists()).toBe(false)
  })
  it('flows prose within paragraphs while retaining plain Chinese section boundaries', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'running' } }); wrappers.push(w)
    store.apply({ eventId: 'start', sequence: 1, runId: 'run', nodeId: 'node', eventType: 'model.started' })
    store.apply({ eventId: 'body', sequence: 2, runId: 'run', nodeId: 'node', eventType: 'model.output.delta', payload: { publicText: '四、质量要求\n设计必须具有业务依据。\n各项设计必须保持一致。\n五、执行约束\n不虚构测试结果。' } })
    store.apply({ eventId: 'end', sequence: 3, runId: 'run', nodeId: 'node', eventType: 'model.completed' })
    await w.vm.$nextTick()
    expect(w.findAll('.run-timeline__text p').map(p => p.text())).toEqual([
      '四、质量要求', '设计必须具有业务依据。\n各项设计必须保持一致。', '五、执行约束', '不虚构测试结果。',
    ])
    store.dispose()
  })
  it('renders thought deltas before structured planner output exists', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'planning' } }); wrappers.push(w)
    store.apply({ eventId: 'start', sequence: 1, runId: 'run', eventType: 'planner.model.started', payload: { stage: 'outline' } })
    store.apply({ eventId: 'thought', sequence: 2, runId: 'run', eventType: 'planner.model.reasoning.delta', payload: { delta: '先厘清冲突，再选择恢复策略。' } })
    store.apply({ eventId: 'activity', sequence: 3, runId: 'run', eventType: 'planner.model.activity' })
    await w.vm.$nextTick()
    expect(w.get('[aria-label="规划器思考过程"]').text()).toContain('先厘清冲突，再选择恢复策略。')
    expect(w.find('.planner-step__draft').exists()).toBe(false)
    expect(w.emitted('content')?.at(-1)).toEqual([true])
    store.apply({ eventId: 'body', sequence: 4, runId: 'run', eventType: 'planner.model.output.delta', payload: { publicText: '策略冲突与依赖分析\n\n高风险人工取舍必须明确列出' } })
    store.apply({ eventId: 'end', sequence: 5, runId: 'run', eventType: 'planner.model.completed' })
    await w.vm.$nextTick()
    expect(w.get('[aria-label="规划器思考过程"]').text()).not.toContain('高风险人工取舍必须明确列出')
    expect(w.get('.planner-step__draft').attributes('open')).toBeUndefined()
    store.dispose()
  })
  it('keeps planner returns as foldable transcript steps when the final plan arrives', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'planning' } }); wrappers.push(w)
    const events = [
      { eventType: 'planner.model.started', payload: { stage: 'intent_profile', callKey: 'intent_profile' } },
      { eventType: 'planner.model.output.delta', payload: { publicText: '先核对任务约束' } },
      { eventType: 'planner.model.completed', payload: { elapsedMs: 1800 } },
      { eventType: 'planner.stage.started', payload: { stage: 'outline', callKey: 'outline' } },
      { eventType: 'planner.model.started', payload: { stage: 'outline', callKey: 'outline' } },
      { eventType: 'planner.model.output.delta', payload: { publicText: '再拆分三个步骤' } },
      { eventType: 'planner.model.completed', payload: {} },
      { eventType: 'planner.completed', payload: {} },
    ]
    events.forEach((event, index) => store.apply({ ...event, eventId: `p-${index}`, runId: 'run', sequence: index + 1, timestamp: new Date(index * 1000).toISOString() }))
    await w.setProps({ plan, status: 'pending' })
    const steps = w.findAll('.planner-step')
    expect(steps).toHaveLength(2)
    expect(steps[0].get('summary').text()).toContain('理解目标与约束')
    expect(steps[1].get('summary').text()).toContain('拟定任务步骤')
    expect(steps.every(step => step.attributes('open') === undefined)).toBe(true)
    expect(w.text()).toContain('先核对任务约束')
    expect(w.text()).toContain('再拆分三个步骤')
    expect(w.get('.run-timeline__plan').text()).toContain('初步规划')
    await w.get('.run-timeline__history-toggle').trigger('click')
    expect(w.get('.run-timeline__plan').isVisible()).toBe(true)
    store.dispose()
  })
  it('loads public text on a terminal Run without starting a ticking clock', async () => {
    vi.useFakeTimers()
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'completed' } }); wrappers.push(w)
    store.apply({ eventId: 'baseline', eventType: 'runtime.display.snapshot', runId: 'run', sequence: 4,
      payload: { schemaVersion: 1, events: [
        { eventId: 'start', eventType: 'model.started', runId: 'run', nodeId: 'node', attemptId: 'a', sequence: 1 },
        { eventId: 'text', eventType: 'model.output.delta', runId: 'run', nodeId: 'node', attemptId: 'a', sequence: 2, payload: { publicText: '断线前已经公开的说明' } },
        { eventId: 'end', eventType: 'node.completed', runId: 'run', nodeId: 'node', attemptId: 'a', sequence: 3 },
        { eventId: 'terminal', eventType: 'run.completed', runId: 'run', sequence: 4 },
      ] } })
    await w.vm.$nextTick()
    expect(w.text()).toContain('断线前已经公开的说明')
    expect(acquireRunRuntimeStore).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
    store.dispose()
  })
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
    const approach = w.get('.run-timeline__approach')
    expect(approach.attributes('open')).toBeUndefined()
    expect(approach.text()).toContain('确认输入')
    expect(approach.text()).toContain('为下游建立共同事实依据')
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
      { kind: 'failed', stage: 'repair', errorCode: 'TASK_PLAN_CONTRACT_FAILED', reasoning_content: 'PRIVATE',
        validationFailures: [
          { stage: 'decompose', code: 'business_objective_required', fieldPath: ['tasks', 0, 'objective'], message: 'PRIVATE' },
          { stage: 'repair', code: 'acceptance_criteria_required', fieldPath: ['tasks', 0, 'acceptanceCriteria'] },
        ] },
    ].map((payload, index) => ({ eventId: `record-${index}`, runId: 'run', stepId: null, eventType: 'task_status_changed',
      observation: null, timestamp: null, durationMs: null, status: null, source: 'trace', payload: { planningProgress: true, ...payload } }))
    const other = { ...traces[0], eventId: 'other', runId: 'other-run', payload: { planningProgress: true, kind: 'plan_parsed', taskCount: 999 } }
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'failed', traces: [...traces, other] } }); wrappers.push(w)
    expect(w.find('.run-timeline__planning-history').exists()).toBe(false)
    expect(w.findAll('.run-timeline__progress-item .chat-recovery').map(p => p.text())).toEqual([
      '已生成任务步骤与规划依据，后续还需校验是否满足任务约束。',
      '本轮规划修正已生成，仍需通过校验后才能进入执行。',
      '本次规划未完成，暂时无法进入执行。',
    ])
    expect(w.text()).toContain('TASK_PLAN_CONTRACT_FAILED')
    expect(w.get('.run-timeline__failure').text()).toContain('首次生成：tasks[0].objective · 缺少明确的任务目标')
    expect(w.get('.run-timeline__failure').text()).toContain('修正后：tasks[0].acceptanceCriteria · 验收条件为空')
    expect(w.text()).not.toContain('PRIVATE')
    expect(w.text()).not.toContain('999')
    expect(acquireRunRuntimeStore).toHaveBeenCalledWith('run')
    expect(w.emitted('content')?.at(-1)).toEqual([true])
  })
  it('shows public planning text and rationale while the run-scoped model is still streaming', async () => {
    vi.useFakeTimers()
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'planning' } }); wrappers.push(w)
    let sequence = 0
    const apply = (eventType: string, payload: Record<string, unknown> = {}) => store.apply({ eventId: `planning-${++sequence}`, sequence,
      eventType, runId: 'run', nodeId: null, attemptId: null, payload })
    apply('planner.stage.started', { stage: 'intent_profile', callKey: 'intent_profile' })
    apply('planner.model.output.delta', { stage: 'intent_profile', callKey: 'intent_profile',
      delta: '{"reasoning_content":"PRIVATE","primaryGoal":"设计实验室管理平台","keyConstraints":["覆盖三个校区"]}' })
    await vi.advanceTimersByTimeAsync(16)
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__planning-text').text()).toContain('设计实验室管理平台')
    expect(w.text()).toContain('理解目标与约束')
    expect(w.text()).not.toContain('PRIVATE')
    apply('planner.profile.resolved', { constraintCount: 7, requiredCapabilityCount: 9, expectedArtifactCount: 2 })
    apply('planner.stage.started', { stage: 'decompose', callKey: 'decompose' })
    apply('planner.model.output.delta', { stage: 'decompose', callKey: 'decompose',
      delta: '{"tasks":[{"key":"internal-key","title":"核对需求","objective":"明确跨校区的数据边界","decompositionRationale":"先统一数据口径，再设计权限' })
    await vi.advanceTimersByTimeAsync(16)
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
  it('keeps task fields in a collapsed draft before plan acceptance', async () => {
    const store = new RunRuntimeStore('run')
    vi.mocked(acquireRunRuntimeStore).mockReturnValue(store)
    const w = mount(CopilotRunTimeline, { props: { runId: 'run', status: 'planning' } }); wrappers.push(w)
    store.apply({ eventId: 'draft', sequence: 1, eventType: 'planner.draft.updated', runId: 'run',
      payload: { stage: 'detail', nodes: [{ key: 'T1', title: '核对数据范围', rationale: '先核对需求再建立模型' }] } })
    await w.vm.$nextTick()
    expect(w.get('.run-timeline__draft').attributes('open')).toBeUndefined()
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
    expect(acquireRunRuntimeStore).toHaveBeenCalledWith('run')
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
    const rows = Array.from(w.get('.agent-work').element.children).filter(el => el.matches('article, details'))
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
    expect(Array.from(w.element.querySelectorAll('.run-timeline__tools, .test-message')).map(el => el.className)).toEqual([
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
