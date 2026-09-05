import type { AcgBlueprint, WorkspaceEntry, WorkspaceGraphNode, WorkspaceMission } from '@/services/api/agentos'
import type { RuntimeObservation, RuntimeTraceObservation, ModelOutputItem } from './observation'
import { projectModelOutput } from './observation'
import { projectRunProgress, type RunProgressTaskGroup } from './runProgress'
import type { RuntimeEventStore, NodeRuntimeState } from './runtimeEvents'

export type RunDocumentSymbolType =
  | 'run'
  | 'planner'
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
  graph?: AcgBlueprint | null
  graphNodes: WorkspaceGraphNode[]
  entries: WorkspaceEntry[]
  runtimeObservation: RuntimeObservation | null
  runtimeStore?: RuntimeEventStore | null
}

const ACTIVE_STATUSES = new Set(['pending', 'queued', 'starting', 'planning', 'running', 'executing', 'retrying'])
const COMPLETED_STATUSES = new Set(['completed', 'succeeded', 'success'])
const FAILED_STATUSES = new Set(['failed', 'cancelled', 'error'])
const STAGE_ORDER = ['intent_profile', 'outline', 'detail', 'relations', 'decompose', 'repair', 'repair_coverage']
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

const asRecord = (value: unknown): Record<string, any> => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
)

const safeText = (value: unknown): string | null => {
  if (typeof value !== 'string' && typeof value !== 'number') return null
  const text = String(value).trim()
  return text ? text.slice(0, 240) : null
}

const safeNumber = (value: unknown): number | null => {
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : null
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

const metricText = (metrics: Record<string, string | number> | undefined, keys: string[]) => {
  if (!metrics) return ''
  return keys
    .map(key => metrics[key] == null ? '' : `${metrics[key]} ${key}`)
    .filter(Boolean)
    .join(' · ')
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

const stageStatus = (items: ModelOutputItem[], liveStage: string | null, stage: string): RunDocumentSymbolStatus => {
  const scoped = items.filter(item => item.stage === stage)
  if (scoped.some(item => item.kind === 'failed' || item.status === 'failed')) return 'failed'
  if (scoped.some(item => item.kind === 'retry' || item.status === 'warning')) return 'warning'
  if (scoped.some(item => item.kind === 'stage_completed')) return 'completed'
  if (scoped.some(item => item.status === 'running') || liveStage === stage) return 'running'
  return 'pending'
}

const latestStageText = (items: ModelOutputItem[], stage: string) => {
  const latest = [...items].reverse().find(item => item.stage === stage)
  return latest?.detail || latest?.title || undefined
}

const plannerResultSymbol = (runId: string, item: ModelOutputItem): RunDocumentSymbol => {
  const metrics: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(item.metrics)) {
    if (value != null) metrics[key] = value
  }
  const title = item.kind === 'plan_parsed'
    ? 'Task Plan'
    : item.kind === 'graph_compiled' ? 'ACG Compile' : 'Intent Profile'
  return symbol({
    id: `result:${runId}:${item.id}`,
    type: 'result',
    status: item.status === 'failed' ? 'failed' : 'completed',
    title,
    subtitle: metricText(metrics, ['taskCount', 'dependencyCount', 'nodeCount', 'edgeCount', 'constraintCount']),
    runId,
    metrics
  })
}

const plannerSymbol = (
  runId: string,
  plannerItems: ModelOutputItem[],
  runtimeStore: RuntimeEventStore | null | undefined,
  traces: RuntimeTraceObservation[],
  graphNodes: WorkspaceGraphNode[],
  graph: AcgBlueprint | null | undefined
): RunDocumentSymbol | null => {
  const planning = runtimeStore?.planning
  const hasPlanner = plannerItems.length > 0 || Boolean(planning && planning.status !== 'IDLE')
  if (!hasPlanner) return null

  const failed = planning?.status === 'FAILED' || plannerItems.some(item => item.status === 'failed')
  const completed = planning?.status === 'COMPLETED' || plannerItems.some(item => item.kind === 'completed')
  const status: RunDocumentSymbolStatus = failed ? 'failed' : completed ? 'completed' : 'running'
  const stages = new Map<string, ModelOutputItem[]>()
  plannerItems.filter(item => item.stage).forEach(item => {
    const stage = item.stage as string
    stages.set(stage, [...(stages.get(stage) || []), item])
  })
  if (planning?.stage && !stages.has(planning.stage)) stages.set(planning.stage, [])
  const stageKeys = [...new Set([...STAGE_ORDER, ...stages.keys()])].filter(stage => stages.has(stage))
  const children: RunDocumentSymbol[] = stageKeys.map(stage => {
    const scoped = stages.get(stage) || []
    const stageStatusValue = stageStatus(plannerItems, planning?.stage || null, stage)
    const stageSymbol = symbol({
      id: `stage:${runId}:${stage}`,
      type: 'stage',
      status: stageStatusValue,
      title: STAGE_LABELS[stage] || stage,
      subtitle: latestStageText(scoped, stage) || (planning?.stage === stage ? LIVE_STAGE_LABELS[stage] : undefined),
      detail: latestStageText(scoped, stage),
      runId,
      metrics: {},
      defaultExpanded: stageStatusValue === 'running' || stageStatusValue === 'failed'
    })
    const result = [...scoped].reverse().find(item => ['profile_resolved', 'plan_parsed'].includes(item.kind))
    if (result) stageSymbol.children.push(plannerResultSymbol(runId, result))
    if (planning?.stage === stage) {
      const liveModel = modelSymbolFromLivePlanning(runId, planning, traces, [...plannerItems].reverse().find(item => item.stage === stage))
      if (liveModel) stageSymbol.children.push(liveModel)
    }
    return stageSymbol
  })

  const graphResult = [...plannerItems].reverse().find(item => item.kind === 'graph_compiled')
  const nodeCount = graphResult?.metrics.nodeCount ?? planning?.graph?.nodeCount ?? graphNodes.length
  const edgeCount = graphResult?.metrics.edgeCount ?? planning?.graph?.edgeCount ?? graph?.edges?.length
  const graphStatus: RunDocumentSymbolStatus = graphResult || graph
    ? 'completed'
    : planning?.draft.nodes.length ? 'running' : 'pending'
  const graphSymbol = symbol({
    id: `acg:${runId}`,
    type: 'acg',
    status: graphStatus,
    title: 'ACG',
    subtitle: [
      planning?.draft.nodes.length && graphStatus === 'running' ? '规划草图' : '',
      nodeCount != null ? `${nodeCount} nodes` : '',
      edgeCount != null ? `${edgeCount} edges` : ''
    ].filter(Boolean).join(' · '),
    runId,
    metrics: {
      ...(nodeCount != null ? { Nodes: nodeCount } : {}),
      ...(edgeCount != null ? { Edges: edgeCount } : {})
    },
    defaultExpanded: false
  })
  const draftNodes = (planning?.draft.nodes || []).map((node, index) => ({
        acgNodeId: node.key,
        nodeType: 'task',
        name: node.title,
        semanticTaskKey: node.key,
        displayOrder: index
      } as WorkspaceGraphNode))
  const outlineNodes = planning?.draft.nodes.length && graphStatus === 'running'
    ? draftNodes
    : graphNodes.length ? graphNodes : draftNodes
  graphSymbol.children = outlineNodes
    .slice()
    .sort((left, right) => left.displayOrder - right.displayOrder)
    .map(node => symbol({
      id: `acg-node:${runId}:${node.acgNodeId}`,
      type: 'acg-node',
      status: statusOf(node.status),
      title: node.name || node.acgNodeId,
      subtitle: node.semanticTaskKey || node.acgNodeId,
      runId,
      semanticTaskKey: node.semanticTaskKey,
      graphNodeId: node.acgNodeId,
      defaultExpanded: false
    }))
  children.push(graphSymbol)
  if (planning?.profile) children.unshift(symbol({
    id: `result:${runId}:live-profile`,
    type: 'result',
    status: 'completed',
    title: 'Intent Profile',
    subtitle: `Profile: ${planning.profile.requiredCapabilityCount ?? 0} capabilities · ${planning.profile.expectedArtifactCount ?? 0} artifacts`,
    runId,
    defaultExpanded: false
  }))
  if (planning?.plan) children.unshift(symbol({
    id: `result:${runId}:live-plan`,
    type: 'result',
    status: 'completed',
    title: 'Task Plan',
    subtitle: `Plan: ${planning.plan.taskCount ?? 0} tasks · ${planning.plan.dependencyCount ?? 0} dependencies`,
    runId,
    defaultExpanded: false
  }))
  const liveModel = planning && planning.stage && !children.some(item => item.children.some(child => child.type === 'model'))
    ? modelSymbolFromLivePlanning(runId, planning, traces)
    : null
  if (liveModel) children.push(liveModel)
  return symbol({
    id: `planner:${runId}`,
    type: 'planner',
    status,
    title: '任务规划',
    subtitle: failed ? `规划失败${plannerItems.find(item => item.detail)?.detail ? ` · ${plannerItems.find(item => item.detail)?.detail}` : ''}` : plannerDigest(plannerItems, planning),
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

const plannerDigest = (items: ModelOutputItem[], planning: NonNullable<RuntimeEventStore['planning']> | undefined) => {
  const parts: string[] = []
  const plan = [...items].reverse().find(item => item.kind === 'plan_parsed')
  const graph = [...items].reverse().find(item => item.kind === 'graph_compiled')
  if (plan) parts.push(plannerResultDigest('Task Plan', plan.metrics))
  if (graph) parts.push(plannerResultDigest('ACG', graph.metrics))
  if (planning?.profile) parts.push(`${planning.profile.requiredCapabilityCount ?? 0} capabilities`)
  if (planning?.plan) parts.push(`${planning.plan.taskCount ?? 0} tasks`)
  if (planning?.graph) parts.push(`${planning.graph.nodeCount ?? 0} nodes`)
  return [...new Set(parts)].join(' · ')
}

const plannerResultDigest = (title: string, metrics: Record<string, any>) => {
  const values = title === 'Task Plan'
    ? [metrics.taskCount != null ? `${metrics.taskCount} Tasks` : '', metrics.dependencyCount != null ? `${metrics.dependencyCount} Dependencies` : '']
    : [metrics.nodeCount != null ? `${metrics.nodeCount} Nodes` : '', metrics.edgeCount != null ? `${metrics.edgeCount} Edges` : '']
  return `${title}${values.filter(Boolean).length ? ` · ${values.filter(Boolean).join(' · ')}` : ''}`
}

const traceAgentName = (traces: RuntimeTraceObservation[], nodeId: string, entry?: WorkspaceEntry) => {
  const metadata = asRecord(entry?.metadata)
  const metadataAgent = safeText(metadata.agentName) || safeText(metadata.agent)
  if (metadataAgent) return metadataAgent
  for (let index = traces.length - 1; index >= 0; index -= 1) {
    const event = traces[index]
    if (event.stepId !== nodeId) continue
    const payload = asRecord(event.payload)
    const agent = safeText(payload.agentName) || safeText(payload.agent) || safeText(payload.agentId)
    if (agent) return agent
  }
  return null
}

const taskModelSymbol = (runId: string, nodeId: string, traces: RuntimeTraceObservation[], nodeState?: NodeRuntimeState) => {
  const modelEvent = [...traces].reverse().find(event => event.stepId === nodeId && (
    event.eventType === 'model_called' || event.eventType === 'model.started' || event.eventType === 'model.completed'
  ))
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

const taskSymbol = (
  runId: string,
  group: RunProgressTaskGroup,
  node: WorkspaceGraphNode | undefined,
  entries: WorkspaceEntry[],
  traces: RuntimeTraceObservation[],
  runtimeStore?: RuntimeEventStore | null
): RunDocumentSymbol => {
  const status: RunDocumentSymbolStatus = group.status === 'success'
    ? 'completed'
    : group.status === 'warning' ? 'warning' : group.status
  const entry = entries.find(item => item.kind === 'task' && (
    item.semanticTaskKey === group.semanticTaskKey || item.acgNodeId === group.graphNodeId
  ))
  const children: RunDocumentSymbol[] = []
  const agent = traceAgentName(traces, group.graphNodeId || '', entry)
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
  const model = taskModelSymbol(runId, group.graphNodeId || '', traces, group.graphNodeId ? runtimeStore?.nodes[group.graphNodeId] : undefined)
  if (model) children.push(model)
  group.tools.forEach(tool => children.push(symbol({
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
  })))
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
      : group.durationMs != null ? formatDuration(group.durationMs) || undefined
        : group.status === 'running' ? 'Running · 正在执行' : undefined,
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
  runtimeStore?: RuntimeEventStore | null
) => {
  const timeline = projectRunProgress(observation, graphNodes)
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
  }, node, entries, observation?.traces || [], runtimeStore))
}

export const projectRunDocument = (input: RunDocumentProjectionInput): RunDocumentModel => {
  const runId = input.runId || input.runtimeObservation?.runId || ''
  if (!runId) return { id: 'run:empty:progress', runId: '', title: input.mission.goal, status: 'pending', symbols: [] }
  const plannerItems = projectModelOutput(input.runtimeObservation?.traces || []).filter(item => (
    item.kind !== 'stage_updated' || item.category === 'runtime'
  ))
  const planner = plannerSymbol(runId, plannerItems, input.runtimeStore, input.runtimeObservation?.traces || [], input.graphNodes, input.graph)
  const tasks = taskGroups(runId, input.runtimeObservation, input.graphNodes, input.entries, input.runtimeStore)
  const symbols = [
    ...(planner ? [planner] : []),
    ...tasks
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
