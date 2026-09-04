import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RunProgressEditor from './RunProgressEditor.vue'
import type { MissionWorkspaceProjection, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import { RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'

const traceEvent = (eventId: string, payload: Record<string, any>, overrides: Partial<{ stepId: string | null; eventType: string; timestamp: string; durationMs: number | null }> = {}) => ({
  eventId,
  runId: 'run_1',
  stepId: overrides.stepId ?? null,
  eventType: overrides.eventType ?? 'task_status_changed',
  observation: null,
  timestamp: overrides.timestamp ?? '2026-09-02T00:00:00Z',
  durationMs: overrides.durationMs ?? null,
  status: String(payload.status || ''),
  payload,
  source: 'trace' as const
})

const observation = (events: ReturnType<typeof traceEvent>[], runStatus: string | null = 'running') => ({
  runId: 'run_1',
  runStatus,
  traces: events,
  events: [],
  communication: [],
  toolCalls: [],
  problems: [],
  audit: {},
  provenance: {},
  operational: null,
  recoveryTrace: [],
  contractViolations: [],
  scheduleTrace: [],
  patchRefs: [],
  lowEntropy: {},
  resourceObservation: null,
  unavailableSources: []
}) as unknown as RuntimeObservation

const plannerEvents = () => [
  traceEvent('e1', { planningProgress: true, category: 'planner', kind: 'started' }),
  traceEvent('e2', {
    planningProgress: true, category: 'planner', kind: 'stage_started',
    stage: 'intent_profile', status: 'started', attempt: 1
  }),
  traceEvent('e3', {
    planningProgress: true, category: 'planner', kind: 'plan_parsed',
    stage: 'planning', status: 'plan_parsed', taskCount: 6, dependencyCount: 8
  }),
  traceEvent('e4', {
    planningProgress: true, category: 'planner', kind: 'graph_compiled',
    nodeCount: 5, edgeCount: 11
  }),
  traceEvent('e5', { planningProgress: true, category: 'planner', kind: 'completed' })
]

const graphNodes = (): WorkspaceGraphNode[] => [
  { acgNodeId: 'node_a', nodeType: 'task', name: '需求分析', semanticTaskKey: 'requirements.analysis', displayOrder: 1 },
  { acgNodeId: 'node_b', nodeType: 'task', name: '架构设计', semanticTaskKey: 'architecture.design', displayOrder: 2 }
] as unknown as WorkspaceGraphNode[]

const entry = (overrides: Partial<WorkspaceEntry> = {}): WorkspaceEntry => ({
  entryId: 'overview:progress',
  kind: 'progress',
  name: '运行进度',
  title: '运行进度',
  group: 'overview',
  displayOrder: -1,
  ...overrides
})

const projection = (overrides: Partial<MissionWorkspaceProjection> = {}): MissionWorkspaceProjection => ({
  mission: { missionId: 'mission_1', goal: '为 IC-200 工业控制器设计完整技术方案', description: '', userId: 'u', metadata: {}, createdAt: '', updatedAt: '', status: 'active' },
  runs: [{ runId: 'run_1', status: 'running', createdAt: '2026-09-02T00:00:00Z', completedAt: null, isActive: true }],
  entries: [
    { entryId: 'graph:main', kind: 'graph', name: 'graph.acg', group: 'overview', displayOrder: 1 },
    {
      entryId: 'artifact:req', kind: 'artifact', name: 'requirements.md', group: 'output', displayOrder: 1,
      semanticTaskKey: 'requirements.analysis', artifactId: 'art_1'
    },
    { entryId: 'overview:graph.acg', kind: 'graph', name: 'graph.acg', group: 'overview', displayOrder: 0 }
  ],
  graphNodes: graphNodes(),
  diagnostics: [],
  ...overrides
} as MissionWorkspaceProjection)

const mountEditor = (props: Record<string, unknown> = {}) => mount(RunProgressEditor, {
  props: {
    entry: entry(),
    projection: projection(),
    graphNodes: graphNodes(),
    runId: 'run_1',
    runtimeObservation: observation(plannerEvents()),
    ...props
  }
})
const runtimeEvent = (sequence: number, eventType: string) => ({
  eventId: `runtime-${sequence}`,
  eventType,
  runId: 'run_1',
  nodeId: null,
  attemptId: null,
  sequence,
  timestamp: new Date(sequence * 1000).toISOString(),
  payload: {}
})

describe('RunProgressEditor', () => {
  it('renders the planner as one aggregated group with deterministic result metrics', () => {
    const wrapper = mountEditor()

    const groups = wrapper.findAll('.run-progress-group')
    expect(groups).toHaveLength(1)
    expect(groups[0].text()).toContain('任务规划')
    // 内部阶段不得一级平铺为用户可读的"正在理解…"文案
    expect(wrapper.text()).not.toContain('正在理解')
    // 完成后组收起，digest 汇总真实计数
    expect(wrapper.text()).toContain('Task Plan · 6 Tasks · 8 Dependencies')
    expect(wrapper.text()).toContain('ACG Compile · 5 Nodes · 11 Edges')
  })

  it('shows the latest planner phase note while planning is still running', () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        traceEvent('e1', { planningProgress: true, category: 'planner', kind: 'started' }),
        traceEvent('e2', {
          planningProgress: true, category: 'planner', kind: 'stage_started',
          stage: 'relations', status: 'started', attempt: 1
        })
      ])
    })

    expect(wrapper.find('.run-progress-group__note').text()).toContain('依赖构建开始')
    expect(wrapper.text()).toContain('RUNNING')
  })

  it('keeps a failed planner group failed without inventing success', () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        traceEvent('e1', { planningProgress: true, category: 'planner', kind: 'started' }),
        traceEvent('e2', {
          planningProgress: true, category: 'planner', kind: 'failed',
          errorCode: 'ACGPlanningError', safeSummary: 'ACGPlanningError during planning'
        })
      ])
    })

    expect(wrapper.text()).toContain('规划失败')
    expect(wrapper.text()).toContain('错误码 ACGPlanningError')
    expect(wrapper.text()).not.toContain('ACGPlanningError during planning'.slice(0, 0) + '规划完成')
  })

  it('renders task groups expanded while running and collapsed with duration once done', async () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        ...plannerEvents(),
        traceEvent('t1', { status: 'started' }, { stepId: 'node_a', eventType: 'step_started' }),
        traceEvent('t2', { status: 'succeeded' }, { stepId: 'node_a', eventType: 'step_succeeded', durationMs: 18000 }),
        traceEvent('t3', { status: 'started' }, { stepId: 'node_b', eventType: 'step_started' }),
        traceEvent('t4', { tool: 'contract_reader', name: 'Read File', status: 'succeeded', latencyMs: 821 }, { stepId: 'node_b', eventType: 'tool_called' })
      ])
    })

    const groups = wrapper.findAll('.run-progress-group')
    expect(groups).toHaveLength(3)
    // running 的任务排在最前，已完成任务收起为摘要行
    const running = groups.find(node => node.text().includes('架构设计'))!
    const done = groups.find(node => node.text().includes('需求分析'))!
    expect(running.classes()).toContain('is-open')
    expect(running.text()).toContain('正在执行')
    expect(running.findAll('.run-progress-tool')).toHaveLength(1)
    expect(running.text()).toContain('Read File')
    expect(running.text()).toContain('821 ms')
    expect(done.classes()).not.toContain('is-open')
    expect(done.text()).toContain('18s')
  })

  it('preserves manual collapse and expand across polling updates', async () => {
    const wrapper = mountEditor({
      runtimeObservation: observation(plannerEvents())
    })
    await wrapper.find('.run-progress-group__head').trigger('click')
    expect(wrapper.find('.run-progress-group').classes()).toContain('is-open')

    // 新一轮 polling 追加事件：用户手动展开的组不得被重新折叠
    await wrapper.setProps({
      runtimeObservation: observation([...plannerEvents(), traceEvent('e9', { planningProgress: true, category: 'planner', kind: 'retry', stage: 'outline', status: 'retrying', attempt: 1, retryCount: 1, errorCode: 'MODEL_TIMEOUT' })])
    })
    expect(wrapper.find('.run-progress-group').classes()).toContain('is-open')

    await wrapper.find('.run-progress-group__head').trigger('click')
    expect(wrapper.find('.run-progress-group').classes()).not.toContain('is-open')
  })

  it('selects the semantic task without forcing an editor switch', async () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        ...plannerEvents(),
        traceEvent('t1', { status: 'started' }, { stepId: 'node_a', eventType: 'step_started' })
      ])
    })

    await wrapper.find('.run-progress-group__head').trigger('click')
    const emitted = wrapper.emitted('selectSemanticTask')
    expect(emitted).toBeTruthy()
    expect(emitted!.at(-1)).toEqual(['requirements.analysis'])
  })

  it('opens the existing graph editor and artifact editor through existing channels', async () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        ...plannerEvents(),
        traceEvent('t1', { status: 'started' }, { stepId: 'node_a', eventType: 'step_started' })
      ])
    })

    // 完成态 planner 组默认收起：先展开才能看到结果子项
    await wrapper.find('.run-progress-group__head').trigger('click')
    await wrapper.find('.run-progress-result__action').trigger('click')
    expect(wrapper.emitted('locateGraph')![0][0]).toMatchObject({ kind: 'graph' })

    const taskGroups = wrapper.findAll('.run-progress-group')
    await taskGroups[1].find('.run-progress-artifact__open').trigger('click')
    expect(wrapper.emitted('openArtifact')![0][0]).toMatchObject({ kind: 'artifact', artifactId: 'art_1' })
  })

  it('renders legacy planningProgress events with engineering wording', () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        traceEvent('legacy_1', { planningProgress: true, stage: 'intent_profile', status: 'started' })
      ])
    })

    expect(wrapper.text()).toContain('意图解析开始')
    expect(wrapper.text()).not.toContain('正在理解')
  })

  it('renders live planner stream facts before Trace projection catches up', () => {
    const runtimeStore = new RunRuntimeStore('run_1')
    runtimeStore.apply(runtimeEvent(1, 'planner.started'))
    runtimeStore.apply({ ...runtimeEvent(2, 'planner.stage.started'), payload: { stage: 'outline', callKey: 'outline' } })
    runtimeStore.apply({ ...runtimeEvent(3, 'planner.model.first_token'), payload: { elapsedMs: 83 } })
    runtimeStore.apply({ ...runtimeEvent(4, 'planner.model.activity'), payload: { elapsedMs: 102, idleMs: 5, receivedChunks: 4, receivedLength: 28 } })
    runtimeStore.apply({ ...runtimeEvent(5, 'planner.profile.resolved'), payload: { requiredCapabilityCount: 2, expectedArtifactCount: 1 } })

    const wrapper = mountEditor({ runtimeObservation: observation([]), runtimeStore })

    expect(wrapper.text()).toContain('PLANNING')
    expect(wrapper.text()).toContain('生成任务骨架')
    expect(wrapper.text()).toContain('模型响应中')
    expect(wrapper.text()).toContain('TTFT 83 ms')
    expect(wrapper.text()).toContain('Idle 5 ms')
    expect(wrapper.text()).toContain('Call outline')
    expect(wrapper.text()).toContain('Profile: 2 capabilities · 1 artifacts')
  })

  it('never renders reasoning, prompt or raw json markers', () => {
    const wrapper = mountEditor({
      runtimeObservation: observation([
        traceEvent('sec_1', {
          planningProgress: true, category: 'planner', kind: 'started',
          prompt: 'SECRET_PROMPT_MARKER', reasoning: 'SECRET_REASONING_MARKER', modelOutput: 'RAW_JSON_MARKER'
        })
      ])
    })

    const html = wrapper.html()
    expect(html).not.toContain('SECRET_PROMPT_MARKER')
    expect(html).not.toContain('SECRET_REASONING_MARKER')
    expect(html).not.toContain('RAW_JSON_MARKER')
  })

  it('shows the empty state without a run instead of pretending progress', () => {
    const wrapper = mountEditor({ runId: null })

    expect(wrapper.text()).toContain('运行开始后，这里会显示任务规划和执行过程。')
    expect(wrapper.text()).not.toContain('等待模型思考')
  })

  it('resolves the run id from a historical run entry itself', () => {
    const wrapper = mountEditor({
      entry: entry({ entryId: 'run_run_9', kind: 'run', name: 'run_9', status: 'failed', runId: 'run_9' }),
      runId: null,
      projection: projection({
        runs: [{ runId: 'run_9', status: 'failed', createdAt: '2026-09-02T00:00:00Z', completedAt: '2026-09-02T00:02:14Z', isActive: false }]
      } as Partial<MissionWorkspaceProjection>),
      runtimeObservation: observation(plannerEvents(), 'failed')
    })

    expect(wrapper.text()).toContain('run_9')
    expect(wrapper.text()).toContain('运行失败')
  })

  it('disables follow-latest on manual scroll up and restores it from the button', async () => {
    const wrapper = mountEditor()
    const body = wrapper.find('.run-progress__body')
    const element = body.element as HTMLElement
    Object.defineProperty(element, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(element, 'scrollTop', { value: 100, configurable: true, writable: true })
    Object.defineProperty(element, 'clientHeight', { value: 400, configurable: true })

    await body.trigger('scroll')
    expect(wrapper.find('.run-progress__follow').exists()).toBe(true)

    await wrapper.find('.run-progress__follow').trigger('click')
    expect(wrapper.find('.run-progress__follow').exists()).toBe(false)
  })
})
