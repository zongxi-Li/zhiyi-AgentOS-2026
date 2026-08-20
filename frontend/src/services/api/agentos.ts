import axios from 'axios'

export const agentosRequest = axios.create({
  baseURL: '/api/agentos/v2',
  timeout: 240000,
  headers: {
    'Content-Type': 'application/json'
  }
})

agentosRequest.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export type WorkflowStatus =
  | 'pending'
  | 'planning'
  | 'running'
  | 'waiting_review'
  | 'retrying'
  | 'failed'
  | 'completed'
  | 'cancelled'
  | 'skipped_by_condition'

export type WorkflowProgressPhase =
  | 'understanding'
  | 'planning'
  | 'graph_building'
  | 'executing'
  | 'recovery'
  | 'review'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface WorkflowProgress {
  taskId: string
  runId: string
  workflowId: string
  status: string
  phase: WorkflowProgressPhase
  message: string
  percent: number | null
  totalSteps: number
  pendingSteps: number
  runningSteps: number
  waitingReviewSteps: number
  retryingSteps: number
  failedSteps: number
  completedSteps: number
  cancelledSteps: number
  currentStepId: string | null
  activeStepIds: string[]
  startedAt: string | null
  updatedAt: string | null
  progress: number
  percentage: number
}

export interface WorkflowRunSummary extends WorkflowProgress {
  source?: string | null
  title?: string | null
  createdAt?: string | null
}

export interface WorkflowExecutionState {
  outputRefs?: Record<string, string>
  outputSummaries?: Record<string, string>
  contextRefs?: Record<string, string>
  memoryRefs?: Record<string, string>
  traceRefs?: Record<string, string>
  provenanceRefs?: Record<string, string>
  graphPatchRefs?: string[]
  resourceBindings?: Record<string, Record<string, unknown>>
  checkpointId?: string | null
  graphVersion?: number
}

export type StepStatus =
  | 'pending'
  | 'running'
  | 'waiting_review'
  | 'retrying'
  | 'failed'
  | 'completed'
  | 'cancelled'
  | 'skipped_by_condition'

export interface AgentTask {
  taskId: string
  title: string
  domain: string
  intent: string
  input: Record<string, any>
  securityLevel: string
  priority: string
  status: WorkflowStatus
  recommendedWorkflow?: string
  enabledPluginIds?: string[] | null
  createdAt?: string
  updatedAt?: string
}

export interface PageResponse<T> {
  items: T[]
  total: number
  page?: number
  pageSize?: number
}

export interface WorkflowStep {
  stepId: string
  name: string
  agentName: string
  capability?: string
  status: StepStatus
  outputRef?: string | null
  outputSummary?: string
  retryCount?: number
  attempt?: number
  maxRetries?: number
  timeout?: number
  priority?: number
  reviewRequired?: boolean
  durationMs?: number
  startedAt?: string
  completedAt?: string
}

export interface Checkpoint {
  checkpointId: string
  version: number
  canResume: boolean
}

export interface TraceEvent {
  eventId: string
  runId: string
  stepId?: string
  agentName?: string
  eventType: string
  observation?: string
  payload?: Record<string, any>
  durationMs?: number
  createdAt?: string
}

export interface WorkflowRun {
  runId: string
  taskId: string
  title?: string | null
  workflowId: string
  workflowSelectionSource?: 'explicit' | 'recommended'
  domain: string
  runtimeEngine?: string
  implementationId?: string
  status: WorkflowStatus
  currentStepId?: string
  steps: WorkflowStep[]
  lifecyclePhase?: WorkflowProgressPhase | null
  lifecycleMessage?: string | null
  outputRef?: string | null
  completedStepIds?: string[]
  activeStepIds?: string[]
  skippedStepIds?: string[]
  executionState?: WorkflowExecutionState
  createdAt?: string
  updatedAt?: string
  startedAt?: string | null
}

export interface WorkflowTraceExport {
  runId: string
  taskId: string
  workflowId: string
  domain: string
  status: WorkflowStatus
  eventCount: number
  events: TraceEvent[]
}

export interface WorkflowStartRequest {
  title: string
  domain: string
  intent: string
  input?: Record<string, any>
  securityLevel?: string
  priority?: string
  workflowId?: string
  reviewMode?: string
  enabledPluginIds?: string[] | null
}

export type WorkflowStartResponse = WorkflowRun

export type ReviewDecision = 'approved' | 'rejected' | 'need_more_info' | 'rerun' | 'cancelled'

export interface ReviewRequest {
  stepId: string
  decision: ReviewDecision
  reviewer?: string
  comment?: string
  operationId?: string
  expectedRunUpdatedAt?: string
  expectedStepStatus?: StepStatus
}

export interface RuntimeAttemptProjection {
  attemptId: string
  attemptNumber: number
  graphVersion?: number
  bindingId?: string
  agentName?: string
  modelName?: string
  status: StepStatus
  startedAt?: string
  endedAt?: string | null
  errorSummary?: string | null
}

export interface ReviewRecord {
  reviewId: string
  runId: string
  stepId: string
  decision: ReviewDecision
  reviewer: string
  comment?: string
  operationId?: string
  traceEventId?: string
  createdAt?: string
}

export interface WorkflowMetric {
  totalRuns: number
  completedRuns: number
  failedRuns: number
  cancelledRuns: number
  waitingReviewRuns: number
  retryingRuns: number
  completionRate: number
  failureRate: number
  recoverySuccessRate: number
  averageRecoveryCount: number
  averageTraceEvents: number
  reviewCount: number
  statusBreakdown: Record<string, number>
}

export interface WorkflowRunQuery {
  status?: WorkflowStatus | ''
  statuses?: string
  domain?: string
  workflowId?: string
  taskId?: string
  lifecyclePhase?: WorkflowProgressPhase | ''
  source?: string
  sources?: string
  summary?: boolean
  page?: number
  pageSize?: number
}

// ===== ACG 动态群体智能引擎可视化视图类型 =====

export interface AcgNode {
  nodeId: string
  nodeType: 'step' | 'agent' | 'skill' | 'memory' | 'evidence' | 'control'
  name?: string
  description?: string
  goal?: string
  agentName?: string
  capability?: string
  controlType?: string
  metadata?: Record<string, any>
}

export interface AcgEdge {
  edgeId: string
  sourceId: string
  targetId: string
  edgeType: 'dependency' | 'communication' | 'control_flow' | 'execution' | 'write' | 'read' | 'support'
  condition?: string
  activation?: 'inactive' | 'active' | 'terminated' | 'superseded'
  metadata?: Record<string, any>
}

export interface AcgBlueprint {
  graphId: string
  taskId?: string
  objective?: string
  complexityLevel?: string
  nodes: AcgNode[]
  edges: AcgEdge[]
  metadata?: Record<string, any>
}

export interface ProvenanceProduction {
  eventId: string
  producerStepId: string
  checksum?: string
  fieldNames?: string[]
  tokenSize?: number
  runId?: string
  taskId?: string
  agentName?: string
  attempt?: number
  previousHash?: string
  eventHash?: string
  createdAt?: string
  evidenceRefs?: string[]
}

export interface AsyncWorkflowStartRequest extends WorkflowStartRequest {
  clientRequestId: string
}

export type AsyncWorkflowStartResponse = WorkflowRun

export class WorkflowApiContractError extends Error {
  readonly code = 'INVALID_ASYNC_WORKFLOW_RESPONSE'

  constructor(message = '异步启动响应缺少有效的 run.runId') {
    super(message)
    this.name = 'WorkflowApiContractError'
  }
}

export interface ProvenanceConsumption {
  eventId: string
  consumerStepId: string
  producerStepIds: string[]
  runId?: string
  taskId?: string
  consumerAgentName?: string
  attempt?: number
  producerEventIds?: string[]
  consumedFields?: string[]
  fieldsByProducer?: Record<string, string[]>
  tokensDelivered?: number
  tokensAvailable?: number
  savingRatio?: number
  contractStatus?: string
  checksum?: string
  previousHash?: string
  eventHash?: string
  createdAt?: string
}

export interface RuntimeInteraction {
  interactionId: string
  eventId: string
  runId?: string
  taskId?: string
  edgeIds: string[]
  producerStepIds: string[]
  consumerStepId: string
  producerAgentNames: string[]
  consumerAgentName: string
  fieldsByProducer: Record<string, string[]>
  tokensDelivered: number
  tokensAvailable: number
  savingRatio: number
  evidenceRefs: string[]
  contractStatus: string
  checksum?: string
  previousHash?: string
  eventHash?: string
  createdAt?: string
}

export interface AcgStepState {
  stepId: string
  status: StepStatus
  agentName: string
  attempt: number
  retryCount: number
  currentBinding?: Record<string, any> | null
  bindingHistory?: Array<Record<string, any>>
  attempts?: RuntimeAttemptProjection[]
  sourcePatchId?: string | null
  createdGraphVersion?: number
  outputVersion?: number
  outputSummary?: string
  errorSummary?: string | null
}

export interface AcgLowEntropyMetrics {
  averageSavingRatio: number
  effectiveSavingRatio: number
  tokensAvailable: number
  tokensDelivered: number
  tokensSaved: number
  recoveryCount: number
  degradationCount?: number
  interactionCount: number
  contractViolationCount: number
  integrityStatus: string
}

export interface AcgDeliverable {
  stepId: string
  name: string
  status: string
  output: Record<string, any>
}

export interface AcgFinalArtifact {
  artifactId: string
  type: string
  title: string
  mediaType: string
  content: string
  structuredData: Record<string, any>
  stepId?: string | null
  legacy?: boolean
}

export interface AcgView {
  runId: string
  status: WorkflowStatus
  engine: string
  acgBlueprint: AcgBlueprint | null
  graphVersion?: number | null
  completedStepIds: string[]
  activeStepIds: string[]
  stepStates: AcgStepState[]
  provenance: {
    schemaVersion?: number
    productions: ProvenanceProduction[]
    consumptions: ProvenanceConsumption[]
    interactions: RuntimeInteraction[]
    integrityStatus?: string
  }
  interactions: RuntimeInteraction[]
  contractViolations: TraceEvent[]
  recoveryTrace: TraceEvent[]
  scheduleTrace: TraceEvent[]
  deliverables: AcgDeliverable[]
  stepOutputs?: AcgDeliverable[]
  finalArtifacts?: AcgFinalArtifact[]
  finalReport: string | null
  lowEntropyMetrics: AcgLowEntropyMetrics
}

const runPath = (runId: string) => `/runs/${encodeURIComponent(runId)}`

const phaseOf = (run: WorkflowRun): WorkflowProgressPhase => {
  if (run.lifecyclePhase) return run.lifecyclePhase
  if (run.status === 'waiting_review') return 'review'
  if (run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled') return run.status
  if (run.status === 'pending' || run.status === 'planning') return 'planning'
  return 'executing'
}

const projectProgress = (run: WorkflowRun): WorkflowProgress => {
  const steps = Array.isArray(run.steps) ? run.steps : []
  const count = (status: StepStatus) => steps.filter(step => step.status === status).length
  const completed = count('completed') + count('skipped_by_condition')
  const total = steps.length
  const percent = total ? Math.round((completed / total) * 10000) / 100 : null
  return {
    taskId: run.taskId,
    runId: run.runId,
    workflowId: run.workflowId,
    status: run.status,
    phase: phaseOf(run),
    message: run.lifecycleMessage || '',
    percent,
    totalSteps: total,
    pendingSteps: count('pending'),
    runningSteps: count('running'),
    waitingReviewSteps: count('waiting_review'),
    retryingSteps: count('retrying'),
    failedSteps: count('failed'),
    completedSteps: completed,
    cancelledSteps: count('cancelled'),
    currentStepId: run.currentStepId || null,
    activeStepIds: run.activeStepIds || [],
    startedAt: run.startedAt || null,
    updatedAt: run.updatedAt || null,
    progress: percent === null ? 0 : percent / 100,
    percentage: percent === null ? 0 : percent
  }
}

const outputMarkdown = (content: Record<string, any>): string | null => {
  for (const key of ['final_answer', 'report_markdown', 'report', 'final_report', 'content']) {
    const value = content[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

const provenanceProjection = (raw: {
  schemaVersion?: number
  integrityStatus?: string
  events?: Array<Record<string, any>>
  productions?: ProvenanceProduction[]
  consumptions?: ProvenanceConsumption[]
  interactions?: RuntimeInteraction[]
}) => {
  const events = Array.isArray(raw.events) ? raw.events : []
  const payloads = events.map(event => ({ eventType: String(event.eventType || ''), ...(event.payload || {}) }))
  const productions = events.length
    ? payloads.filter(item => item.producerStepId && !item.consumerStepId) as unknown as ProvenanceProduction[]
    : (Array.isArray(raw.productions) ? raw.productions : [])
  const consumptions = events.length
    ? payloads.filter(item => item.consumerStepId && !item.interactionId) as unknown as ProvenanceConsumption[]
    : (Array.isArray(raw.consumptions) ? raw.consumptions : [])
  const interactions = events.length
    ? payloads.filter(item => item.interactionId) as unknown as RuntimeInteraction[]
    : (Array.isArray(raw.interactions) ? raw.interactions : [])
  return { schemaVersion: raw.schemaVersion, integrityStatus: raw.integrityStatus, productions, consumptions, interactions }
}

export interface WorkflowHistoryConfig {
  runId: string
  title?: string | null
  reviewMode?: string
  enabledPluginIds?: string[]
  input?: Record<string, unknown>
}

export const agentosApi = {
  async listWorkflowRuns(
    params: WorkflowRunQuery = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<PageResponse<WorkflowRunSummary>> {
    const response = await agentosRequest.get<PageResponse<WorkflowRun>>('/runs', {
      params: {
        status: params.status || undefined,
        statuses: params.statuses || undefined,
        domain: params.domain,
        workflowId: params.workflowId,
        taskId: params.taskId,
        lifecyclePhase: params.lifecyclePhase || undefined,
        source: params.source,
        sources: params.sources,
        summary: params.summary,
        page: params.page,
        pageSize: params.pageSize
      },
      signal: options.signal
    })
    return {
      ...response.data,
      items: response.data.items.map(run => ({
        ...projectProgress(run),
        title: run.title,
        createdAt: run.createdAt
      }))
    }
  },

  async startWorkflow(payload: WorkflowStartRequest): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>('/runs', payload)
    return response.data
  },

  async startWorkflowAsync(
    payload: AsyncWorkflowStartRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>('/runs', payload, { signal: options.signal })
    if (!response.data?.runId || !response.data.taskId) {
      throw new WorkflowApiContractError('运行创建响应缺少 runId 或 taskId')
    }
    return response.data
  },

  async getWorkflowProgress(
    runId: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowProgress> {
    return projectProgress(await this.getWorkflowRun(runId, options))
  },

  async getWorkflowRun(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowRun> {
    const response = await agentosRequest.get<WorkflowRun>(runPath(runId), {
      signal: options.signal
    })
    return response.data
  },

  async getWorkflowHistoryConfig(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowHistoryConfig> {
    const response = await agentosRequest.get<WorkflowHistoryConfig>(`${runPath(runId)}/history-config`, {
      signal: options.signal
    })
    return response.data
  },

  async listWorkflowCheckpoints(runId: string, options: { signal?: AbortSignal } = {}): Promise<PageResponse<Checkpoint> & { runId: string }> {
    const response = await agentosRequest.get<PageResponse<Checkpoint> & { runId: string }>(`${runPath(runId)}/checkpoints`, { signal: options.signal })
    return response.data
  },

  async getWorkflowTrace(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowTraceExport> {
    const response = await agentosRequest.get<WorkflowTraceExport>(`${runPath(runId)}/trace`, { signal: options.signal })
    return response.data
  },

  async exportWorkflowTraceMarkdown(runId: string): Promise<string> {
    const trace = await this.getWorkflowTrace(runId)
    return ['# AgentOS Trace', '', ...trace.events.map(event =>
      `- ${event.createdAt || ''} **${event.eventType}**${event.stepId ? ` · ${event.stepId}` : ''}`
    )].join('\n')
  },

  async listWorkflowReviews(runId: string, options: { signal?: AbortSignal } = {}): Promise<PageResponse<ReviewRecord> & { runId: string }> {
    const response = await agentosRequest.get<PageResponse<ReviewRecord> & { runId: string }>(`${runPath(runId)}/reviews`, { signal: options.signal })
    return response.data
  },

  async applyWorkflowReview(runId: string, payload: ReviewRequest, options: { signal?: AbortSignal } = {}): Promise<WorkflowRun> {
    const request = { ...payload, operationId: payload.operationId || crypto.randomUUID() }
    const response = await agentosRequest.post<WorkflowRun>(`${runPath(runId)}/reviews`, request, { signal: options.signal })
    return response.data
  },

  async getAcgView(runId: string, options: { signal?: AbortSignal; run?: WorkflowRun | Promise<WorkflowRun> } = {}): Promise<AcgView> {
    const [run, graphResponse, provenanceResponse, trace] = await Promise.all([
      options.run || this.getWorkflowRun(runId, options),
      agentosRequest.get<any>(`${runPath(runId)}/graph`, { signal: options.signal }),
      agentosRequest.get<any>(`${runPath(runId)}/provenance`, { signal: options.signal }),
      this.getWorkflowTrace(runId, options)
    ])
    const graph = graphResponse.data
    const provenance = provenanceProjection(provenanceResponse.data)
    const outputRefs = Object.entries(run.executionState?.outputRefs || {}) as Array<[string, string]>
    const outputs = outputRefs.length
      ? await Promise.all(outputRefs.map(async ([stepId, outputRef]) => {
        const response = await agentosRequest.get<{ content: Record<string, any> }>(
          `${runPath(runId)}/outputs/${encodeURIComponent(outputRef)}`,
          { signal: options.signal }
        )
        const step = run.steps.find(item => item.stepId === stepId)
        return { stepId, name: step?.name || stepId, status: step?.status || 'completed', output: response.data.content }
      }))
      : (await agentosRequest.get<{
          items: Array<{ stepId: string; name: string; status: StepStatus; content: Record<string, any> }>
        }>(`${runPath(runId)}/legacy-outputs`, { signal: options.signal })).data.items.map(item => ({
          stepId: item.stepId,
          name: item.name,
          status: item.status,
          output: item.content
        }))
    const interactions = provenance.interactions
    const tokensAvailable = interactions.reduce((sum, item) => sum + Number(item.tokensAvailable || 0), 0)
    const tokensDelivered = interactions.reduce((sum, item) => sum + Number(item.tokensDelivered || 0), 0)
    const reports = outputs.map(item => outputMarkdown(item.output)).filter((item): item is string => Boolean(item))
    const finalReport = reports.length ? reports[reports.length - 1] : null
    const finalArtifacts = outputs.flatMap(item => {
      const artifact = item.output.artifact
      if (!artifact || typeof artifact !== 'object') return []
      const candidate = artifact as Record<string, unknown>
      if (typeof candidate.artifactId !== 'string' || typeof candidate.content !== 'string') return []
      return [{
        artifactId: candidate.artifactId,
        type: typeof candidate.type === 'string' ? candidate.type : 'report',
        title: typeof candidate.title === 'string' ? candidate.title : item.name,
        mediaType: typeof candidate.mediaType === 'string' ? candidate.mediaType : 'text/markdown',
        content: candidate.content,
        structuredData: candidate.structuredData && typeof candidate.structuredData === 'object'
          ? candidate.structuredData as Record<string, any>
          : {},
        stepId: item.stepId
      } satisfies AcgFinalArtifact]
    })
    return {
      runId,
      status: run.status,
      engine: run.runtimeEngine || 'acg',
      acgBlueprint: graph as AcgBlueprint,
      graphVersion: graph.graphVersion,
      completedStepIds: run.completedStepIds || [],
      activeStepIds: run.activeStepIds || [],
      stepStates: run.steps.map(step => ({
        stepId: step.stepId,
        status: step.status,
        agentName: step.agentName,
        attempt: step.attempt || 0,
        retryCount: step.retryCount || 0,
        currentBinding: run.executionState?.resourceBindings?.[step.stepId] || null,
        outputSummary: step.outputSummary
      })),
      provenance,
      interactions,
      contractViolations: trace.events.filter(event => event.eventType === 'contract_violation'),
      recoveryTrace: trace.events.filter(event => ['step_failed', 'run_recovered', 'run_degraded'].includes(event.eventType)),
      scheduleTrace: trace.events.filter(event => event.eventType.includes('schedule') || event.eventType.includes('superstep')),
      deliverables: outputs,
      stepOutputs: outputs,
      finalArtifacts,
      finalReport,
      lowEntropyMetrics: {
        averageSavingRatio: interactions.length ? interactions.reduce((sum, item) => sum + Number(item.savingRatio || 0), 0) / interactions.length : 0,
        effectiveSavingRatio: tokensAvailable ? (tokensAvailable - tokensDelivered) / tokensAvailable : 0,
        tokensAvailable,
        tokensDelivered,
        tokensSaved: Math.max(0, tokensAvailable - tokensDelivered),
        recoveryCount: trace.events.filter(event => event.eventType === 'run_recovered').length,
        interactionCount: interactions.length,
        contractViolationCount: trace.events.filter(event => event.eventType === 'contract_violation').length,
        integrityStatus: provenance.integrityStatus || 'invalid'
      }
    }
  }
}
