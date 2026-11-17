import type { WorkspaceGraphNode } from '@/services/api/agentos'
import type { ModelOutputItem, RuntimeObservation } from './observation'
import { projectModelOutput } from './observation'

export interface RunProgressMetrics {
  taskCount?: number
  dependencyCount?: number
  nodeCount?: number
  edgeCount?: number
  constraintCount?: number
  latencyMs?: number
  durationMs?: number
}

export interface RunProgressItem {
  id: string
  timestamp: string | null
  category: 'planner' | 'task' | 'tool'
  kind: string
  status: 'running' | 'success' | 'warning' | 'failed'
  title: string
  summary: string | null
  semanticTaskKey: string | null
  graphNodeId: string | null
  toolName: string | null
  metrics: RunProgressMetrics
}

export interface RunProgressPlannerGroup {
  category: 'planner'
  status: 'running' | 'success' | 'warning' | 'failed'
  headline: string
  /** 运行中的阶段/重试说明；完成后仅保留带真实计数的确定性结果。 */
  phaseNotes: string[]
  /** 最新阶段的模型调用预算（秒），来自真实事件 payload；帮助用户建立等待预期。 */
  phaseBudgetSeconds: number | null
  results: RunProgressItem[]
}

export interface RunProgressTaskGroup {
  category: 'task'
  status: 'pending' | 'running' | 'success' | 'warning' | 'failed'
  title: string
  semanticTaskKey: string | null
  graphNodeId: string | null
  durationMs: number | null
  errorCode: string | null
  tools: RunProgressItem[]
  previousFailures?: RunProgressTaskFailure[]
}

export interface RunProgressTaskFailure {
  eventId: string
  timestamp: string | null
  attemptId: string | null
  errorCode: string
  durationMs: number | null
}

export interface RunProgressTimeline {
  planner: RunProgressPlannerGroup | null
  tasks: RunProgressTaskGroup[]
  startedAt: string | null
}

const numberOf = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === '') return undefined
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : undefined
}

const durationOf = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

const durationBetween = (startedAt: string | null | undefined, finishedAt: string | null | undefined) => {
  if (!startedAt || !finishedAt) return null
  const started = Date.parse(startedAt)
  const finished = Date.parse(finishedAt)
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished <= started) return null
  return finished - started
}

const PLANNER_RESULT_KINDS = new Set(['plan_parsed', 'graph_compiled', 'profile_resolved'])

/**
 * Project Runtime Observation into the user-level Run timeline.
 *
 * Planner 内部阶段（intent_profile/outline/detail/relations）聚合为一个
 * "任务规划"组：运行中展示阶段说明，完成后仅保留确定性结果子项（Task
 * Plan / ACG Compile）。Task/Tool 事实来自 Runtime Trace 的 step/tool
 * 事件；数量永远来自事件 payload 与真实对象，缺失时不显示数字。
 */
export const projectRunProgress = (
  observation: RuntimeObservation | null,
  graphNodes: WorkspaceGraphNode[],
  projectedPlannerItems?: ModelOutputItem[]
): RunProgressTimeline => {
  const traces = observation?.traces || []
  const plannerItems = projectedPlannerItems ?? projectModelOutput(traces).filter(item => (
    item.kind !== 'stage_updated' || item.category === 'runtime'
  ))

  const results: RunProgressItem[] = []
  const phaseNotes: string[] = []
  let groupStatus: RunProgressPlannerGroup['status'] = plannerItems.length ? 'running' : 'running'
  let phaseBudgetSeconds: number | null = null
  let hasPlanner = false
  for (const item of plannerItems) {
    hasPlanner = true
    if (item.category === 'planner' && PLANNER_RESULT_KINDS.has(item.kind)) {
      results.push({
        id: item.id,
        timestamp: item.timestamp,
        category: 'planner',
        kind: item.kind,
        status: 'success',
        title: item.kind === 'plan_parsed'
          ? 'Task Plan'
          : item.kind === 'graph_compiled' ? 'ACG Compile' : 'Task Profile',
        summary: null,
        semanticTaskKey: null,
        graphNodeId: null,
        toolName: null,
        metrics: { ...item.metrics }
      })
      continue
    }
    if (item.category === 'planner' && item.kind === 'failed') {
      groupStatus = 'failed'
      phaseNotes.push(item.title + (item.detail ? ` · ${item.detail}` : ''))
      continue
    }
    if (item.category === 'planner' && item.kind === 'retry') {
      groupStatus = 'warning'
      phaseNotes.push(item.title + (item.detail ? ` · ${item.detail}` : ''))
      continue
    }
    if (item.category === 'planner' && item.kind === 'completed') {
      if (groupStatus !== 'failed') groupStatus = 'success'
      continue
    }
    if (item.kind === 'stage_started' || item.kind === 'stage_updated') {
      phaseBudgetSeconds = item.metrics.timeoutSeconds ?? phaseBudgetSeconds
    }
    phaseNotes.push(item.title)
  }

  const planner: RunProgressPlannerGroup | null = hasPlanner ? {
    category: 'planner',
    status: groupStatus,
    headline: groupStatus === 'failed' ? '规划失败' : '任务规划',
    phaseNotes: phaseNotes.reverse(),
    phaseBudgetSeconds,
    results
  } : null

  // A trace stepId may be the blueprint node id, task id, or semantic key.
  // Resolve all of them to the same graph node before grouping activity.
  const nodeByLookupId = new Map<string, WorkspaceGraphNode>()
  graphNodes.forEach(node => {
    nodeByLookupId.set(node.acgNodeId, node)
    if (node.taskId) nodeByLookupId.set(node.taskId, node)
    if (node.semanticTaskKey) nodeByLookupId.set(node.semanticTaskKey, node)
  })
  const nodeForStep = (stepId: string | null) => stepId ? nodeByLookupId.get(stepId) : undefined
  const taskKinds = new Set(['step_started', 'step_succeeded', 'step_completed', 'step_failed'])
  const tasks = new Map<string, RunProgressTaskGroup>()
  const taskStartedAt = new Map<string, string>()
  const failures = new Map<string, RunProgressTaskFailure[]>()
  const tools: RunProgressItem[] = []
  const ensureTask = (stepId: string, node?: WorkspaceGraphNode) => {
    const graphNodeId = node?.acgNodeId || stepId
    const existing = tasks.get(graphNodeId)
    if (existing) return { group: existing, graphNodeId }
    const group: RunProgressTaskGroup = {
      category: 'task',
      status: 'running',
      title: node?.name || stepId,
      semanticTaskKey: node?.semanticTaskKey || null,
      graphNodeId,
      durationMs: null,
      errorCode: null,
      tools: []
    }
    tasks.set(graphNodeId, group)
    return { group, graphNodeId }
  }
  for (const event of traces) {
    if (event.payload.planningProgress) continue
    const stepId = event.stepId
    if (event.eventType === 'tool_called') {
      if (!stepId) continue
      const node = nodeForStep(stepId)
      const { graphNodeId } = ensureTask(stepId, node)
      tools.push({
        id: event.eventId,
        timestamp: event.timestamp,
        category: 'tool',
        kind: 'tool_called',
        status: event.payload.status === 'failed' ? 'failed' : 'success',
        title: String(event.payload.name || event.payload.tool || 'Tool'),
        summary: null,
        semanticTaskKey: node?.semanticTaskKey || null,
        graphNodeId,
        toolName: String(event.payload.tool || event.payload.name || ''),
        metrics: { latencyMs: numberOf(event.payload.latencyMs) }
      })
      continue
    }
    if (!stepId || !taskKinds.has(event.eventType)) continue
    const node = nodeForStep(stepId)
    const { group, graphNodeId } = ensureTask(stepId, node)
    if (event.eventType === 'step_started') {
      group.status = 'running'
      group.errorCode = null
      group.durationMs = null
      if (event.timestamp) taskStartedAt.set(graphNodeId, event.timestamp)
    } else if (event.eventType === 'step_failed') {
      group.status = 'failed'
      group.errorCode = String(event.payload.errorCode || 'STEP_FAILED')
      group.durationMs = durationOf(event.durationMs)
        ?? durationOf(event.payload.durationMs)
        ?? durationBetween(taskStartedAt.get(graphNodeId), event.timestamp)
      const failure: RunProgressTaskFailure = {
        eventId: event.eventId,
        timestamp: event.timestamp,
        attemptId: typeof event.payload.attemptId === 'string' ? event.payload.attemptId : null,
        errorCode: group.errorCode,
        durationMs: group.durationMs
      }
      failures.set(graphNodeId, [...(failures.get(graphNodeId) || []), failure])
    } else {
      // A failed event belongs to one attempt. A later completion is the
      // current task state after retry, so historical failures must not make
      // the projection permanently failed.
      group.status = 'success'
      group.errorCode = null
      group.durationMs = durationOf(event.durationMs)
        ?? durationOf(event.payload.durationMs)
        ?? durationBetween(taskStartedAt.get(graphNodeId), event.timestamp)
    }
  }
  for (const tool of tools) {
    const owner = tool.graphNodeId ? tasks.get(tool.graphNodeId) : undefined
    if (owner) owner.tools.push(tool)
  }

  // Trace exports can omit a retry's start while retaining its previous failure.
  // Current execution facts own the task status; traces still own its history.
  const run = observation?.run?.runId === observation?.runId ? observation?.run : null
  const steps = new Map(run?.steps.map(step => [step.stepId, step]) || [])
  const tree = observation?.executionTree?.run.runId === observation?.runId ? observation?.executionTree : null
  const statusFor = (status: string | null | undefined): RunProgressTaskGroup['status'] | null => {
    if (['running', 'retrying', 'executing', 'planning'].includes(status || '')) return 'running'
    if (['completed', 'succeeded', 'success'].includes(status || '')) return 'success'
    if (status === 'failed') return 'failed'
    if (status === 'waiting_review' || status === 'cancelled') return 'warning'
    if (status === 'pending') return 'pending'
    return null
  }
  for (const [nodeId, group] of tasks) {
    const node = nodeByLookupId.get(nodeId)
    const step = steps.get(nodeId)
    const attempts = tree?.nodes.find(item => item.acgNodeId === nodeId)?.attempts || []
    const currentAttempt = node?.attemptId
      ? attempts.find(item => item.attempt.attemptId === node.attemptId)?.attempt
      : attempts.find(item => item.attempt.attemptNumber === (step?.attempt ?? -1) + 1)?.attempt
    const currentAttemptId = currentAttempt?.attemptId || node?.attemptId || null
    const startedAt = currentAttempt?.startedAt || step?.startedAt
    const started = startedAt ? Date.parse(startedAt) : NaN
    const historical = (failure: RunProgressTaskFailure) => (
      Boolean(failure.attemptId && currentAttemptId && failure.attemptId !== currentAttemptId)
      || Boolean(failure.timestamp && Number.isFinite(started) && Date.parse(failure.timestamp) < started)
    )
    const status = statusFor(step?.status || (node?.status === 'pending' ? null : node?.status))
    const recorded = failures.get(nodeId) || []
    const latestFailure = recorded[recorded.length - 1]
    if (status) {
      const tracedStatus = group.status
      group.status = status
      group.errorCode = status === 'failed'
        ? latestFailure && !historical(latestFailure) ? latestFailure.errorCode : 'STEP_FAILED'
        : null
      group.durationMs = status === 'success' || status === 'failed'
        ? durationOf(step?.durationMs) ?? (tracedStatus === status
          && (status !== 'failed' || !latestFailure || !historical(latestFailure)) ? group.durationMs : null)
        : null
    }
    group.previousFailures = recorded.filter(failure => (
      group.status !== 'failed' || failure !== latestFailure || historical(failure)
    ))
  }

  return {
    planner,
    tasks: [...tasks.values()],
    startedAt: traces[0]?.timestamp || null
  }
}
