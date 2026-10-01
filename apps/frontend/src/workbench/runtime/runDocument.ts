import type { GraphProjection, WorkspaceEntry, WorkspaceGraphNode, WorkspaceMission } from '@/services/api/agentos'
import type { RuntimeObservation, RuntimeTraceObservation, ModelOutputItem } from './observation'
import { projectModelOutput } from './observation'
import { projectRunProgress, type RunProgressTaskGroup } from './runProgress'
import type { RuntimeEventStore, NodeRuntimeState } from './runtimeEvents'
import { isRunDeliverableEntry } from './deliverableIdentity'

export type RunDocumentSymbolType =
  | 'run'
  | 'planner'
  | 'execution'
  | 'stage'
  | 'task'
  | 'agent'
  | 'model'
  | 'tool'
  | 'artifact'
  | 'acg'
  | 'acg-node'
  | 'result'
  | 'runtime'

export type RunDocumentSymbolStatus = 'pending' | 'running' | 'completed' | 'warning' | 'failed'
export type RunDocumentViewKey = 'intent-profile' | 'task-plan' | 'detail' | 'relations'

export interface RunDocumentSymbol {
  id: string
  type: RunDocumentSymbolType
  status: RunDocumentSymbolStatus
  title: string
  subtitle?: string
  detail?: string
  runId: string
  semanticTaskKey?: string | null
  graphNodeId?: string | null
  artifactKey?: string | null
  artifactId?: string | null
  viewKey?: RunDocumentViewKey
  metrics?: Record<string, string | number>
  children: RunDocumentSymbol[]
  /** Used only for first appearance. A user's explicit fold choice wins. */
  defaultExpanded?: boolean
  /** Safe, structured content. Sensitive keys are removed before it reaches the editor. */
  content?: string | null
}

export interface RunDocumentModel {
  id: string
  runId: string
  title: string
  status: RunDocumentSymbolStatus
  symbols: RunDocumentSymbol[]
}

export interface RunDocumentProjectionInput {
  runId: string | null
  mission: WorkspaceMission
  graph?: GraphProjection | null
  graphNodes: WorkspaceGraphNode[]
  entries: WorkspaceEntry[]
  runtimeObservation: RuntimeObservation | null
  runtimeStore?: RuntimeEventStore | null
}

const ACTIVE_STATUSES = new Set(['pending', 'queued', 'starting', 'planning', 'running', 'executing', 'retrying'])
const COMPLETED_STATUSES = new Set(['completed', 'succeeded', 'success'])
const FAILED_STATUSES = new Set(['failed', 'cancelled', 'error'])
const STAGE_ORDER = ['intent_profile', 'outline', 'detail', 'relations']
const STAGE_LABELS: Record<string, string> = {
  intent_profile: 'Intent Profile',
  outline: 'Task Plan',
  detail: 'Detail',
  relations: 'Relations',
  decompose: 'Decompose',
  repair: 'Repair',
  repair_coverage: 'Coverage Repair'
}
const LIVE_STAGE_LABELS: Record<string, string> = {
  intent_profile: '解析任务意图',
  outline: '生成任务骨架',
  detail: '补全任务细节',
  relations: '整理依赖关系',
  decompose: '拆分执行任务',
  repair: '修复规划结构',
  repair_coverage: '补全引用覆盖'
}
const SENSITIVE_KEY = /(?:reasoning|chain[_-]?of[_-]?thought|hidden[_-]?prompt|system[_-]?prompt|credential|password|secret|api[_-]?key|authorization|bearer|token)/i
const SENSITIVE_MARKER = /(?:reasoning_content|chain_of_thought|hidden_prompt|system_prompt|credential|SECRET_REASONING_MARKER|SECRET_SYSTEM_PROMPT|SECRET_CREDENTIAL)/i
const MODEL_EVENT_TYPES = new Set(['model_called', 'model.started', 'model.completed'])

interface RunTraceIndex {
  latestAgentByNode: Map<string, string>
  latestModelEventByNode: Map<string, RuntimeTraceObservation>
}

const asRecord = (value: unknown): Record<string, any> => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
)

const safeText = (value: unknown): string | null => {
  if (typeof value !== 'string' && typeof value !== 'number') return null
  const text = String(value).trim()
  return text ? text.slice(0, 240) : null
}

const safeNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : null
}

const buildRunTraceIndex = (traces: RuntimeTraceObservation[]): RunTraceIndex => {
  const latestAgentByNode = new Map<string, string>()
  const latestModelEventByNode = new Map<string, RuntimeTraceObservation>()
  for (let index = traces.length - 1; index >= 0; index -= 1) {
    const event = traces[index]
    const nodeId = event.stepId
    if (!nodeId) continue
    if (!latestModelEventByNode.has(nodeId) && MODEL_EVENT_TYPES.has(event.eventType)) {
      latestModelEventByNode.set(nodeId, event)
    }
    if (!latestAgentByNode.has(nodeId)) {
      const payload = asRecord(event.payload)
      const agent = safeText(payload.agentName) || safeText(payload.agent) || safeText(payload.agentId)
      if (agent) latestAgentByNode.set(nodeId, agent)
    }
  }
  return { latestAgentByNode, latestModelEventByNode }
}

const statusOf = (value: unknown): RunDocumentSymbolStatus => {
  const status = String(value || '').toLowerCase()
  if (FAILED_STATUSES.has(status)) return 'failed'
  if (COMPLETED_STATUSES.has(status)) return 'completed'
  if (status === 'warning' || status === 'waiting_review') return 'warning'
  if (ACTIVE_STATUSES.has(status)) return 'running'
  return 'pending'
}

const symbol = (value: Omit<RunDocumentSymbol, 'children'> & { children?: RunDocumentSymbol[] }): RunDocumentSymbol => ({
  children: [],
  ...value
})

const formatDuration = (value: unknown) => {
  const ms = safeNumber(value)
  if (ms == null) return null
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${Number((ms / 1000).toFixed(1))}s`
}

const scrubStructuredValue = (value: unknown, depth = 0): unknown => {
  if (depth > 8) return '[depth limited]'
  if (Array.isArray(value)) return value.map(item => scrubStructuredValue(item, depth + 1))
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !SENSITIVE_KEY.test(key))
    .map(([key, item]) => [key, scrubStructuredValue(item, depth + 1)]))
}

/**
 * The Run editor receives only a safe structured projection. We intentionally
 * drop an unparseable payload containing sensitive markers instead of trying
 * to guess whether it is a model answer or hidden reasoning.
 */
export const safeStructuredOutput = (value: unknown): string | null => {
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const parsed = JSON.parse(value)
    return JSON.stringify(scrubStructuredValue(parsed), null, 2)
  } catch {
    if (SENSITIVE_MARKER.test(value)) return null
    return value.slice(0, 65536)
  }
}

const plannerModelName = (traces: RuntimeTraceObservation[], liveModelName?: unknown) => {
  const live = safeText(liveModelName)
  if (live) return live
  for (let index = traces.length - 1; index >= 0; index -= 1) {
    const payload = asRecord(traces[index].payload)
    if (!payload.planningProgress) continue
    const model = safeText(payload.modelName) || safeText(payload.model)
    if (model) return model
  }
  return 'Planner model'
}

const plannerModelMetrics = (planning: NonNullable<RuntimeEventStore['planning']>, latest?: ModelOutputItem) => {
  const metrics: Record<string, string | number> = {}
  const attempt = planning.retryIndex + 1 || latest?.attempt
  if (attempt != null) metrics.Attempt = attempt
  if (planning.ttftMs != null) metrics.TTFT = planning.ttftMs
  if (planning.idleMs != null) metrics.Idle = planning.idleMs
  if (planning.chunkCount > 0) metrics.Chunks = planning.chunkCount
  if (planning.elapsedMs != null) metrics.Duration = formatDuration(planning.elapsedMs) || planning.elapsedMs
  if (planning.callKey) metrics.Call = planning.callKey
  return metrics
}

const modelSymbolFromLivePlanning = (
  runId: string,
  planning: NonNullable<RuntimeEventStore['planning']>,
  traces: RuntimeTraceObservation[],
  latestPlannerItem?: ModelOutputItem
): RunDocumentSymbol | null => {
  if (planning.status === 'IDLE') return null
  const status: RunDocumentSymbolStatus = planning.status === 'FAILED'
    ? 'failed'
    : planning.status === 'COMPLETED' ? 'completed' : 'running'
  const metrics = plannerModelMetrics(planning, latestPlannerItem)
  const model = symbol({
    id: `model:${runId}:${planning.callKey || planning.stage || 'planning'}:${planning.retryIndex + 1}`,
    type: 'model',
    status,
    title: plannerModelName(traces, null),
    subtitle: [
      planning.modelPhase === 'ACTIVE' ? '模型响应中' : planning.modelPhase === 'WAITING_FIRST_TOKEN' ? '等待模型首 token' : '',
      metrics.Attempt != null ? `Attempt ${metrics.Attempt}` : '',
      metrics.Chunks != null ? `${metrics.Chunks} chunks` : '',
      metrics.Duration != null ? String(metrics.Duration) : ''
    ].filter(Boolean).join(' · '),
    runId,
    metrics,
    defaultExpanded: status === 'running'
  })
  const output = safeStructuredOutput(planning.outputBuffer)
  if (output) {
    model.children.push(symbol({
      id: `${model.id}:structured-output`,
      type: 'runtime',
      status: planning.status === 'FAILED' ? 'failed' : 'completed',
      title: 'Structured Output',
      subtitle: 'Raw Structured Output',
      runId,
      content: output,
      defaultExpanded: false
    }))
  }
  return model
}

const stageItems = (items: ModelOutputItem[], stage: string) => items.filter(item => (
  item.stage === stage
  || (stage === 'intent_profile' && item.kind === 'profile_resolved')
  || (stage === 'outline' && item.kind === 'plan_parsed')
))

const stageStatus = (items: ModelOutputItem[], liveStage: string | null, stage: string): RunDocumentSymbolStatus => {
  const scoped = stageItems(items, stage)
  if (scoped.some(item => item.kind === 'failed' || item.status === 'failed')) return 'failed'
  if (scoped.some(item => item.kind === 'retry' || item.status === 'warning')) return 'warning'
  if (scoped.some(item => ['stage_completed', 'profile_resolved', 'plan_parsed'].includes(item.kind))) return 'completed'
  if (scoped.some(item => item.status === 'running') || liveStage === stage) return 'running'
  return 'pending'
}

const latestStageText = (items: ModelOutputItem[], stage: string) => {
  const latest = [...stageItems(items, stage)].reverse()[0]
  return latest?.detail || latest?.title || undefined
}

const plannerItemMetrics = (item?: ModelOutputItem | null): Record<string, string | number> => {
  const metrics: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(item?.metrics || {})) {
    if (value != null) metrics[key] = value
  }
  return metrics
}

const plannerSymbol = (
  runId: string,
  plannerItems: ModelOutputItem[],
  runtimeStore: RuntimeEventStore | null | undefined,
  traces: RuntimeTraceObservation[],
  graphNodes: WorkspaceGraphNode[],
  graph: GraphProjection | null | undefined
): RunDocumentSymbol | null => {
  const planning = runtimeStore?.planning
  // A materialized graph is a verified planning output. The planner event
  // stream can arrive late (or be unavailable after a reconnect), so do not
  // regress an already compiled plan to the fallback "Waiting" state.
  const hasCompiledGraph = plannerItems.some(item => item.kind === 'graph_compiled')
    || Boolean(graph)
    || graphNodes.length > 0
  const hasPlannerProjection = plannerItems.length > 0 || Boolean(planning && planning.status !== 'IDLE')
  const hasPlanner = hasPlannerProjection || hasCompiledGraph
  if (!hasPlanner) return null

  const failed = planning?.status === 'FAILED' || plannerItems.some(item => item.status === 'failed')
  const completed = planning?.status === 'COMPLETED'
    || plannerItems.some(item => ['completed', 'graph_compiled'].includes(item.kind))
    || (hasCompiledGraph && !hasPlannerProjection)
  const status: RunDocumentSymbolStatus = failed ? 'failed' : completed ? 'completed' : 'running'
  const stages = new Map<string, ModelOutputItem[]>()
  plannerItems.forEach(item => {
    const stage = STAGE_ORDER.includes(item.stage as string)
      ? item.stage as string
      : item.kind === 'profile_resolved' ? 'intent_profile'
        : item.kind === 'plan_parsed' ? 'outline' : null
    if (stage) stages.set(stage, [...(stages.get(stage) || []), item])
  })
  const children: RunDocumentSymbol[] = hasPlannerProjection ? STAGE_ORDER.map(stage => {
    const scoped = stages.get(stage) || []
    const result = [...scoped].reverse().find(item => ['profile_resolved', 'plan_parsed'].includes(item.kind))
    const observedStatus = stageStatus(plannerItems, planning?.stage || null, stage)
    const stageStatusValue = observedStatus === 'pending' && (
      (stage === 'intent_profile' && Boolean(planning?.profile))
      || (stage === 'outline' && Boolean(planning?.plan))
    ) ? 'completed' : observedStatus
    const stageMetrics: Record<string, string | number> = {
      ...(stage === 'intent_profile' && planning?.profile ? {
        constraintCount: planning.profile.constraintCount ?? 0,
        requiredCapabilityCount: planning.profile.requiredCapabilityCount ?? 0,
        expectedArtifactCount: planning.profile.expectedArtifactCount ?? 0
      } : {}),
      ...(stage === 'outline' && planning?.plan ? {
        taskCount: planning.plan.taskCount ?? 0,
        dependencyCount: planning.plan.dependencyCount ?? 0
      } : {}),
      ...plannerItemMetrics(result)
    }
    const stageSymbol = symbol({
      id: `stage:${runId}:${stage}`,
      type: 'stage',
      status: stageStatusValue,
      title: STAGE_LABELS[stage] || stage,
      subtitle: latestStageText(scoped, stage) || (planning?.stage === stage ? LIVE_STAGE_LABELS[stage] : undefined),
      detail: latestStageText(scoped, stage) || (planning?.stage === stage ? LIVE_STAGE_LABELS[stage] : undefined),
      runId,
      viewKey: stage === 'intent_profile' ? 'intent-profile' : stage === 'outline' ? 'task-plan' : stage === 'detail' ? 'detail' : stage === 'relations' ? 'relations' : undefined,
      metrics: stageMetrics,
      defaultExpanded: stageStatusValue === 'running' || stageStatusValue === 'failed'
    })
    if (planning?.stage === stage) {
      const liveModel = modelSymbolFromLivePlanning(runId, planning, traces, [...plannerItems].reverse().find(item => item.stage === stage))
      if (liveModel) stageSymbol.children.push(liveModel)
    }
    return stageSymbol
  }) : []

  return symbol({
    id: `planner:${runId}`,
    type: 'planner',
    status,
    title: 'Planning',
    subtitle: failed
      ? `规划失败${plannerItems.find(item => item.detail)?.detail ? ` · ${plannerItems.find(item => item.detail)?.detail}` : ''}`
      : plannerDigest(plannerItems, planning) || (completed ? 'Planning completed' : undefined),
    detail: failed ? plannerItems.find(item => item.detail)?.detail || '规划失败' : undefined,
    runId,
    metrics: {
      ...(planning?.plan?.taskCount != null ? { 'Task Count': planning.plan.taskCount } : {}),
      ...(planning?.plan?.dependencyCount != null ? { 'Dependency Count': planning.plan.dependencyCount } : {}),
      ...(planning?.retryIndex != null ? { Attempt: planning.retryIndex + 1 } : {})
    },
    children,
    defaultExpanded: status === 'running' || status === 'failed'
  })
}

const acgSymbol = (
  runId: string,
  plannerItems: ModelOutputItem[],
  runtimeStore: RuntimeEventStore | null | undefined,
  graphNodes: WorkspaceGraphNode[],
  graph: GraphProjection | null | undefined
): RunDocumentSymbol => {
  const planning = runtimeStore?.planning
  const graphResult = [...plannerItems].reverse().find(item => item.kind === 'graph_compiled')
  // An empty graphNodes projection means that ACG has not materialized yet;
  // it must not be presented as a verified "0 nodes" graph.
  const projectedNodeCount = graphNodes.length > 0 ? graphNodes.length : null
  const nodeCount = graphResult?.metrics.nodeCount ?? planning?.graph?.nodeCount ?? projectedNodeCount
  const edgeCount = graphResult?.metrics.edgeCount ?? planning?.graph?.edgeCount ?? graph?.edges?.length
  const compiled = Boolean(graphResult || graph || graphNodes.length)
  const status: RunDocumentSymbolStatus = compiled
    ? 'completed'
    : planning?.draft.nodes.length ? 'running' : 'pending'
  const subtitle = compiled
    ? [nodeCount != null ? `${nodeCount} nodes` : '', edgeCount != null ? `${edgeCount} edges` : ''].filter(Boolean).join(' · ') || 'Compiled'
    : planning?.draft.nodes.length ? 'Compiling' : 'Waiting for compilation'
  return symbol({
    id: `acg:${runId}`,
    type: 'acg',
    status,
    title: 'ACG',
    subtitle,
    runId,
    metrics: {
      ...(nodeCount != null ? { Nodes: nodeCount } : {}),
      ...(edgeCount != null ? { Edges: edgeCount } : {})
    },
    defaultExpanded: false
  })
}

const plannerDigest = (items: ModelOutputItem[], planning: NonNullable<RuntimeEventStore['planning']> | undefined) => {
  const parts: string[] = []
  const plan = [...items].reverse().find(item => item.kind === 'plan_parsed')
  if (plan) parts.push(plannerResultDigest('Task Plan', plan.metrics))
  if (planning?.profile) parts.push(`${planning.profile.requiredCapabilityCount ?? 0} capabilities`)
  if (planning?.plan) parts.push(`${planning.plan.taskCount ?? 0} tasks`)
  return [...new Set(parts)].join(' · ')
}

const plannerResultDigest = (title: string, metrics: Record<string, any>) => {
  const values = title === 'Task Plan'
    ? [metrics.taskCount != null ? `${metrics.taskCount} Tasks` : '', metrics.dependencyCount != null ? `${metrics.dependencyCount} Dependencies` : '']
    : [metrics.nodeCount != null ? `${metrics.nodeCount} Nodes` : '', metrics.edgeCount != null ? `${metrics.edgeCount} Edges` : '']
  return `${title}${values.filter(Boolean).length ? ` · ${values.filter(Boolean).join(' · ')}` : ''}`
}

const traceAgentName = (traceIndex: RunTraceIndex, nodeId: string, entry?: WorkspaceEntry) => {
  const metadata = asRecord(entry?.metadata)
  const metadataAgent = safeText(metadata.agentName) || safeText(metadata.agent)
  if (metadataAgent) return metadataAgent
  return traceIndex.latestAgentByNode.get(nodeId) || null
}

const taskModelSymbol = (
  runId: string,
  nodeId: string,
  semanticTaskKey: string | null,
  traceIndex: RunTraceIndex,
  nodeState?: NodeRuntimeState
) => {
  const modelEvent = traceIndex.latestModelEventByNode.get(nodeId)
  const payload = asRecord(modelEvent?.payload)
  const modelName = safeText(nodeState?.modelName) || safeText(payload.modelName) || safeText(payload.model)
  if (!modelEvent && !modelName && !nodeState) return null
  const attemptId = safeText(payload.attemptId) || safeText(nodeState?.currentAttemptId) || 'latest'
  const status = nodeState?.status === 'FAILED'
    ? 'failed'
    : nodeState?.status === 'COMPLETED' ? 'completed'
      : modelEvent?.eventType === 'model.completed' ? 'completed' : 'running'
  const model = symbol({
    id: `model:${attemptId}`,
    type: 'model',
    status,
    title: modelName || 'Model call',
    subtitle: [
      payload.attempt != null ? `Attempt ${payload.attempt}` : '',
      nodeState?.chunkCount ? `${nodeState.chunkCount} chunks` : '',
      formatDuration(modelEvent?.durationMs) || ''
    ].filter(Boolean).join(' · '),
    runId,
    semanticTaskKey,
    graphNodeId: nodeId,
    metrics: {
      ...(payload.attempt != null ? { Attempt: Number(payload.attempt) } : {}),
      ...(nodeState?.chunkCount ? { Chunks: nodeState.chunkCount } : {})
    },
    defaultExpanded: status === 'running'
  })
  const output = safeStructuredOutput(nodeState?.outputBuffer)
  if (output) model.children.push(symbol({
    id: `${model.id}:structured-output`,
    type: 'runtime',
    status: status === 'failed' ? 'failed' : 'completed',
    title: 'Structured Output',
    subtitle: 'Raw Structured Output',
    runId,
    graphNodeId: nodeId,
    content: output,
    defaultExpanded: false
  }))
  return model
}

const taskToolSymbol = (
  runId: string,
  group: RunProgressTaskGroup,
  tool: RunProgressTaskGroup['tools'][number]
): RunDocumentSymbol => symbol({
  id: `tool:${runId}:${tool.id}`,
  type: 'tool',
  status: tool.status === 'failed' ? 'failed' : 'completed',
  title: tool.title,
  subtitle: [tool.metrics.latencyMs != null ? `${tool.metrics.latencyMs} ms` : '', tool.toolName || ''].filter(Boolean).join(' · '),
  runId,
  semanticTaskKey: group.semanticTaskKey,
  graphNodeId: group.graphNodeId,
  metrics: {
    ...(tool.metrics.latencyMs != null ? { Duration: tool.metrics.latencyMs } : {}),
    Task: group.title
  },
  defaultExpanded: false
})

const taskSymbol = (
  runId: string,
  group: RunProgressTaskGroup,
  node: WorkspaceGraphNode | undefined,
  entries: WorkspaceEntry[],
  traceIndex: RunTraceIndex,
  runtimeStore?: RuntimeEventStore | null
): RunDocumentSymbol => {
  const status: RunDocumentSymbolStatus = group.status === 'success'
    ? 'completed'
    : group.status === 'warning' ? 'warning' : group.status
  const entry = entries.find(item => item.kind === 'task' && (
    item.semanticTaskKey === group.semanticTaskKey || item.acgNodeId === group.graphNodeId
  ))
  const children: RunDocumentSymbol[] = []
  const agent = traceAgentName(traceIndex, group.graphNodeId || '', entry)
  if (agent) children.push(symbol({
    id: `agent:${runId}:${group.graphNodeId}:${agent}`,
    type: 'agent',
    status,
    title: 'Agent',
    subtitle: agent,
    runId,
    semanticTaskKey: group.semanticTaskKey,
    graphNodeId: group.graphNodeId,
    defaultExpanded: false
  }))
  const model = taskModelSymbol(
    runId,
    group.graphNodeId || '',
    group.semanticTaskKey,
    traceIndex,
    group.graphNodeId ? runtimeStore?.nodes[group.graphNodeId] : undefined
  )
  const toolSymbols = group.tools.map(tool => taskToolSymbol(runId, group, tool))
  if (model) {
    // Model calls own the tools emitted with the same stepId. This makes the
    // invocation chain visible as Task -> Model -> Tool instead of reporting
    // Activity 0 on the model while showing unrelated sibling rows on Task.
    model.children.unshift(...toolSymbols)
    if (toolSymbols.length) {
      model.metrics = { ...(model.metrics || {}), Tools: toolSymbols.length }
    }
    children.push(model)
  } else {
    // Some historical traces have tool events but no model_called event. Keep
    // those tools visible directly under the task rather than dropping them.
    children.push(...toolSymbols)
  }
  const artifactCount = entries.filter(item => item.kind === 'artifact' && (
    (group.semanticTaskKey && item.semanticTaskKey === group.semanticTaskKey)
    || (group.graphNodeId && item.acgNodeId === group.graphNodeId)
    || (entry?.entryId && item.parentEntryId === entry.entryId)
  )).length
  entries
    .filter(item => item.kind === 'artifact' && (
      (group.semanticTaskKey && item.semanticTaskKey === group.semanticTaskKey)
      || (group.graphNodeId && item.acgNodeId === group.graphNodeId)
      || (entry?.entryId && item.parentEntryId === entry.entryId)
    ))
    .sort((left, right) => left.displayOrder - right.displayOrder || left.entryId.localeCompare(right.entryId))
    .forEach(artifact => children.push(symbol({
      id: `artifact:${artifact.artifactKey || artifact.artifactId || artifact.entryId}`,
      type: 'artifact',
      status: 'completed',
      title: artifact.name,
      subtitle: artifact.artifactType || artifact.mediaType || undefined,
      runId,
      semanticTaskKey: artifact.semanticTaskKey,
      graphNodeId: artifact.acgNodeId || group.graphNodeId,
      artifactKey: artifact.artifactKey,
      artifactId: artifact.artifactId,
      metrics: { Task: group.title },
      defaultExpanded: false
    })))
  if (group.errorCode) children.push(symbol({
    id: `result:${runId}:${group.graphNodeId}:error`,
    type: 'result',
    status: 'failed',
    title: 'Result',
    subtitle: group.errorCode,
    detail: group.errorCode,
    runId,
    graphNodeId: group.graphNodeId,
    defaultExpanded: true
  }))
  return symbol({
    id: `task:${group.semanticTaskKey || group.graphNodeId || group.title}`,
    type: 'task',
    status,
    title: group.title,
    subtitle: group.status === 'failed'
      ? group.errorCode || 'Execution failed'
      : [
        group.durationMs != null ? formatDuration(group.durationMs) : '',
        artifactCount ? `${artifactCount} artifact${artifactCount === 1 ? '' : 's'}` : '',
        group.status === 'running' ? 'Running' : ''
      ].filter(Boolean).join(' · ') || undefined,
    detail: group.errorCode || undefined,
    runId,
    semanticTaskKey: group.semanticTaskKey,
    graphNodeId: group.graphNodeId,
    metrics: {
      ...(group.durationMs != null ? { Duration: group.durationMs } : {}),
      ...(group.semanticTaskKey ? { semanticTaskKey: group.semanticTaskKey } : {}),
      ...(node?.attemptId ? { Attempt: node.attemptId } : {})
    },
    children,
    defaultExpanded: status === 'running' || status === 'warning' || status === 'failed'
  })
}

const taskGroups = (
  runId: string,
  observation: RuntimeObservation | null,
  graphNodes: WorkspaceGraphNode[],
  entries: WorkspaceEntry[],
  plannerItems: ModelOutputItem[],
  traceIndex: RunTraceIndex,
  runtimeStore?: RuntimeEventStore | null
) => {
  const timeline = projectRunProgress(observation, graphNodes, plannerItems)
  const groups = new Map(timeline.tasks.map(task => [task.graphNodeId, task]))
  const nodeList = graphNodes
    .filter(node => ['task', 'step'].includes(node.nodeType) || groups.has(node.acgNodeId))
    .slice()
    .sort((left, right) => left.displayOrder - right.displayOrder)
  return nodeList.map(node => taskSymbol(runId, groups.get(node.acgNodeId) || {
    category: 'task',
    status: statusOf(node.status) as RunProgressTaskGroup['status'],
    title: node.name || node.acgNodeId,
    semanticTaskKey: node.semanticTaskKey || null,
    graphNodeId: node.acgNodeId,
    durationMs: null,
    errorCode: null,
    tools: []
  }, node, entries, traceIndex, runtimeStore))
}

const artifactSymbol = (runId: string, artifact: WorkspaceEntry): RunDocumentSymbol => symbol({
  id: `artifact:${artifact.artifactKey || artifact.artifactId || artifact.entryId}`,
  type: 'artifact',
  status: 'completed',
  title: artifact.name,
  subtitle: artifact.artifactType || artifact.mediaType || undefined,
  runId,
  semanticTaskKey: artifact.semanticTaskKey,
  graphNodeId: artifact.acgNodeId,
  artifactKey: artifact.artifactKey,
  artifactId: artifact.artifactId,
  detail: isRunDeliverableEntry(artifact) ? 'Run deliverable' : 'Supporting artifact',
  defaultExpanded: isRunDeliverableEntry(artifact)
})

const executionStatus = (tasks: RunDocumentSymbol[]): RunDocumentSymbolStatus => {
  if (tasks.some(task => task.status === 'failed')) return 'failed'
  if (tasks.some(task => task.status === 'running')) return 'running'
  if (tasks.some(task => task.status === 'warning')) return 'warning'
  if (tasks.length && tasks.every(task => task.status === 'completed')) return 'completed'
  return 'pending'
}

export const projectRunDocument = (input: RunDocumentProjectionInput): RunDocumentModel => {
  const runId = input.runId || input.runtimeObservation?.runId || ''
  if (!runId) return { id: 'run:empty:progress', runId: '', title: input.mission.goal, status: 'pending', symbols: [] }
  const traces = input.runtimeObservation?.traces || []
  const plannerItems = projectModelOutput(traces).filter(item => (
    item.kind !== 'stage_updated' || item.category === 'runtime'
  ))
  const traceIndex = buildRunTraceIndex(traces)
  const planner = plannerSymbol(runId, plannerItems, input.runtimeStore, traces, input.graphNodes, input.graph)
  const tasks = taskGroups(runId, input.runtimeObservation, input.graphNodes, input.entries, plannerItems, traceIndex, input.runtimeStore)
  const planning = planner || symbol({
    id: `planner:${runId}`,
    type: 'planner',
    status: 'pending',
    title: 'Planning',
    subtitle: 'Waiting for planning',
    runId,
    defaultExpanded: false
  })
  const execution = symbol({
    id: `execution:${runId}`,
    type: 'execution',
    status: executionStatus(tasks),
    title: 'Execution',
    subtitle: tasks.length ? `${tasks.length} tasks` : 'Waiting for tasks',
    runId,
    metrics: { 'Task Count': tasks.length },
    children: tasks,
    defaultExpanded: tasks.some(task => task.status === 'running' || task.status === 'warning' || task.status === 'failed')
  })
  const artifactEntries = input.entries
    .filter(entry => entry.kind === 'artifact')
  const finalArtifacts = artifactEntries.filter(isRunDeliverableEntry)
  const supportingArtifacts = artifactEntries.filter(entry => !isRunDeliverableEntry(entry))
  const artifacts = [...finalArtifacts, ...supportingArtifacts]
    .sort((left, right) => (
      Number(isRunDeliverableEntry(right)) - Number(isRunDeliverableEntry(left))
      || left.displayOrder - right.displayOrder
      || left.entryId.localeCompare(right.entryId)
    ))
    .map(artifact => artifactSymbol(runId, artifact))
  const result = symbol({
    id: `result:${runId}`,
    type: 'result',
    status: finalArtifacts.length ? 'completed' : artifactEntries.length ? 'warning' : 'pending',
    title: 'Result',
    subtitle: finalArtifacts.length
      ? `${finalArtifacts.length} final deliverable${finalArtifacts.length === 1 ? '' : 's'} · ${supportingArtifacts.length} supporting artifact${supportingArtifacts.length === 1 ? '' : 's'}`
      : artifactEntries.length
        ? `Final deliverable missing · ${supportingArtifacts.length} supporting artifact${supportingArtifacts.length === 1 ? '' : 's'}`
        : 'Final deliverable missing',
    runId,
    children: artifacts,
    defaultExpanded: finalArtifacts.length > 0
  })
  const symbols = [
    planning,
    acgSymbol(runId, plannerItems, input.runtimeStore, input.graphNodes, input.graph),
    execution,
    result
  ]
  const runStatus = input.runtimeObservation?.runStatus || ''
  return {
    id: `run:${runId}:progress`,
    runId,
    title: input.mission.goal,
    status: statusOf(runStatus),
    symbols
  }
}

export const findRunDocumentSymbol = (symbols: RunDocumentSymbol[], id: string | null): RunDocumentSymbol | null => {
  if (!id) return null
  for (const item of symbols) {
    if (item.id === id) return item
    const nested = findRunDocumentSymbol(item.children, id)
    if (nested) return nested
  }
  return null
}
