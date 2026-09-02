import axios from 'axios'
import { apiUrl } from '@/platform'

export const agentosRequest = axios.create({
  baseURL: apiUrl('/api/agentos/v2'),
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
  missionId: string
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
  completedStepIds?: string[]
  startedAt: string | null
  updatedAt: string | null
  runtimeRevision?: number
  progress: number
  percentage: number
}

export interface WorkflowRunSummary extends WorkflowProgress {
  source?: string | null
  title?: string | null
  createdAt?: string | null
}

export interface WorkflowExecutionState {
  parentRunId?: string | null
  sourceRunId?: string | null
  rerunReason?: string | null
  supersedesRunId?: string | null
  supersededByRunId?: string | null
  sourcePatchId?: string | null
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
  reviewPayload?: Record<string, unknown> | null
  consensusResults?: Record<string, Record<string, unknown>>
  controlFrames?: Array<Record<string, unknown>>
  loopIterations?: Record<string, number>
  loopPaths?: Record<string, number[]>
  planningDiversity?: 'stable' | 'balanced' | 'exploratory'
  planningSeed?: number | null
  plannerAlgorithmVersion?: string | null
  planningCandidateCount?: number
  selectedPlanningVariantId?: string | null
  selectedCapabilities?: string[]
  selectedBindings?: Array<Record<string, string>>
  planningSelectionReasons?: string[]
  requestedCapabilityProfile?: 'auto' | 'standard' | 'full'
  effectiveCapabilityProfile?: 'standard' | 'full'
  capabilityProfileReason?: string
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

export interface RuntimeMissionRecord {
  missionId: string
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

/** One row in the canonical Project list. A Mission owns its Runs. */
export interface MissionListItem {
  missionId: string
  userId: string
  title: string
  description: string
  status: string
  latestRunId?: string | null
  latestRunStatus?: string | null
  createdAt: string
  updatedAt: string
  runCount: number
}

export interface MissionListQuery {
  status?: string
  page?: number
  pageSize?: number
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
  missionId: string
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
  acgBlueprint?: AcgBlueprint | null
  createdAt?: string
  updatedAt?: string
  runtimeRevision?: number
  startedAt?: string | null
  planningDiversity?: 'stable' | 'balanced' | 'exploratory'
  planningSeed?: number | null
  plannerAlgorithmVersion?: string | null
  planningCandidateCount?: number
  selectedPlanningVariantId?: string | null
}

export interface WorkflowTraceExport {
  runId: string
  missionId: string
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
  materialRefs?: string[]
}

export interface ContentManifestSummary {
  manifestId: string
  kind: 'material' | 'intermediate' | 'artifact'
  mediaType: string
  checksum?: string | null
  byteLength: number
  fragmentCount: number
  estimatedTokens?: number | null
  chunkingVersion: string
  sealed: boolean
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

export type NodeExecutionPhase =
  | 'prepared'
  | 'executed'
  | 'audited'
  | 'committed'
  | 'waiting_review'
  | 'failed'
  | 'cancelled'

export interface NodeExecutionRecord {
  operationId: string
  executionInstanceId: string
  runId: string
  stepId: string
  attemptId: string
  phase: NodeExecutionPhase
  artifactRefs: Record<string, string>
  auditRef?: string | null
  commitId?: string | null
  loopPath: number[]
  failureCode?: string | null
}

export interface IdentitySemanticTask {
  taskId: string
  missionId: string
  semanticTaskKey?: string | null
  parentTaskId?: string | null
  title: string
  objective: string
  constraints: Array<Record<string, unknown>>
  status: string
  metadata: Record<string, unknown>
}

export interface IdentityAttempt {
  attemptId: string
  runId: string
  taskId: string
  status: string
  attemptNumber: number
  startedAt?: string | null
  finishedAt?: string | null
  failureReason?: string | null
}

export interface IdentityStepExecution {
  stepExecutionId: string
  runId: string
  taskId: string
  attemptId: string
  status: string
  startedAt?: string | null
  finishedAt?: string | null
}

export interface ExecutionBinding {
  bindingId: string
  attemptId: string
  acgNodeId: string
  resourceId: string
  agentId: string
  modelId: string
  metadata: Record<string, unknown>
  createdAt?: string
}

export type RuntimeResourceType = 'agent' | 'model' | 'embedding' | 'tool' | 'worker' | 'skill' | string
export type RuntimeResourceHealth = 'unknown' | 'online' | 'degraded' | 'offline' | string
export type RuntimeDeploymentTier = 'local' | 'terminal' | 'edge' | 'cloud' | string

export interface RuntimeResourceEndpoint {
  protocol: 'local' | 'http' | 'https' | 'grpc' | string
  address: string
}

export interface RuntimeComputeCapacity {
  cpuCores: number
  memoryMb: number
  gpuType?: string | null
  gpuMemoryMb: number
  bandwidthMbps: number
}

export interface RuntimeResourceProfile {
  resourceId: string
  resourceType: RuntimeResourceType
  deploymentTier?: RuntimeDeploymentTier | null
  capabilities: string[]
  domains: string[]
  labels: Record<string, string>
  location?: string | null
  dataZone?: string | null
  costMetadata: Record<string, number>
  capacity: number
  ownerScope?: string | null
  privacyLevel?: string | null
  executionEndpoint?: RuntimeResourceEndpoint | null
  computeCapacity?: RuntimeComputeCapacity
  modelIds?: string[]
  enabled: boolean
  metadata: Record<string, unknown>
  version: number
}

export interface RuntimeResourceSnapshot {
  resourceId: string
  observedAt: string
  availableSlots: number
  utilization: number
  healthStatus: RuntimeResourceHealth
  reliability?: number | null
  latencyMs?: number | null
  metrics: Record<string, number>
}

export interface RuntimeResourceItem {
  profile: RuntimeResourceProfile
  snapshot: RuntimeResourceSnapshot
  snapshotVersion: number
}

export interface RunProvenanceEvent {
  eventType?: string
  payload?: Record<string, any>
  createdAt?: string | null
}

export interface RunProvenanceProjection {
  runId: string
  integrityStatus?: string
  events?: RunProvenanceEvent[]
  productions?: ProvenanceProduction[]
  consumptions?: ProvenanceConsumption[]
  interactions?: RuntimeInteraction[]
  legacy?: boolean
}

export interface ResourceBindingObservation extends ExecutionBinding {
  taskId: string
  semanticTaskKey?: string | null
  attemptNumber: number
  attemptStatus: string
  startedAt?: string | null
  finishedAt?: string | null
  deploymentTier: RuntimeDeploymentTier | null
  placementReasons: string[]
  scoreFactors: Record<string, number>
}

export interface ResourceFailoverObservation {
  eventId: string
  stepId: string | null
  timestamp: string | null
  failedResources: Array<{
    stepId?: string
    resourceId: string
    error?: string | null
  }>
  retryStepIds: string[]
}

export interface ResourceObservation {
  runId: string
  items: RuntimeResourceItem[]
  bindings: ResourceBindingObservation[]
  attemptCount: number
  source: string
  failoverEvents: ResourceFailoverObservation[]
}

export interface IdentityAttemptDetail {
  attempt: IdentityAttempt
  executionBinding?: ExecutionBinding | null
  executions: IdentityStepExecution[]
}

export interface RunExecutionNode {
  task: IdentitySemanticTask
  acgNodeId?: string | null
  attempts: IdentityAttemptDetail[]
}

export interface CompiledPackageIdentity {
  packageId: string
  packageVersion: number
  checksum: string
  blueprintHash?: string | null
}

export interface RunLineage {
  parentRunId?: string | null
  sourceRunId?: string | null
  rerunReason?: string | null
  supersedesRunId?: string | null
  supersededByRunId?: string | null
  sourcePatchId?: string | null
}

export interface RunOperationalState {
  package?: CompiledPackageIdentity | null
  lineage: RunLineage
  nodeExecutions: NodeExecutionRecord[]
  controlFrames: Array<Record<string, unknown>>
  communicationRefs: string[]
  memoryRefs: string[]
  evidenceRefs: string[]
  leaseStatuses: Record<string, string>
  loopIterations: Record<string, number>
  consensusResults: Record<string, Record<string, unknown>>
  debateSessions: Record<string, Record<string, unknown>>
  recoveryOutcome?: Record<string, unknown> | null
}

export interface IdentityBlueprint {
  blueprintId: string
  missionId: string
  version: number
  graphId: string
  graph: Record<string, unknown>
  createdAt?: string
  metadata: Record<string, unknown>
}

export interface IdentityWorkflowRun {
  runId: string
  missionId: string
  blueprintId: string
  status: string
  graphVersion: number
  startedAt?: string | null
  finishedAt?: string | null
  createdAt?: string
  updatedAt?: string
  metadata: Record<string, unknown>
}

export interface RunExecutionTree {
  run: IdentityWorkflowRun
  blueprint: IdentityBlueprint
  nodes: RunExecutionNode[]
  operational: RunOperationalState
}

export interface IdentityProjectionHealth {
  status: 'healthy' | 'degraded'
  source: string
  backlogCount: number
  failedCount: number
  oldestEventAt?: string | null
  unappliedEventCount: number
  inboxBacklog: number
  outboxBacklog: number
  startupReconciliation: {
    examinedMissions: number
    examinedRuns: number
    repairedMissions: number
    repairedRuns: number
    replayedEvents: number
    failureCount: number
  }
}

export interface IdentityProjectionState {
  status: 'available' | 'pending' | 'unavailable'
  message?: string
}

export type WorkspaceEntryKind = 'folder' | 'graph' | 'virtual_document' | 'task' | 'artifact' | 'run' | 'progress'
export type WorkspaceIdentityQuality = 'canonical' | 'legacy'
export type WorkspaceRunStatus = WorkflowStatus | 'succeeded' | 'superseded'

export interface WorkspaceMission {
  missionId: string
  userId: string
  goal: string
  description: string
  metadata: Record<string, unknown>
  createdAt: string
  updatedAt: string
  status: string
}

export interface WorkspaceRunSummary {
  runId: string
  status: WorkspaceRunStatus
  parentRunId?: string | null
  sourceRunId?: string | null
  createdAt: string
  completedAt?: string | null
  isActive: boolean
}

export interface WorkspaceEntry {
  entryId: string
  kind: WorkspaceEntryKind
  name: string
  title?: string | null
  group: 'overview' | 'steps' | 'output' | 'runs' | string
  parentEntryId?: string | null
  displayOrder: number
  semanticTaskKey?: string | null
  artifactKey?: string | null
  taskId?: string | null
  logicalRole?: string | null
  objective?: string | null
  dependencyKeys?: string[]
  attemptCount?: number
  latestAttemptId?: string | null
  artifactCount?: number
  artifactId?: string | null
  contentRef?: string | null
  artifactType?: string | null
  mediaType?: string | null
  checksum?: string | null
  attemptId?: string | null
  acgNodeId?: string | null
  disposition?: 'GENERATED' | 'REUSED' | string | null
  sourceRunId?: string | null
  identityQuality?: WorkspaceIdentityQuality | null
  createdAt?: string | null
  runId?: string | null
  status?: string | null
  blueprintId?: string | null
  graphId?: string | null
  graphVersion?: number | null
  parentRunId?: string | null
  completedAt?: string | null
  isActive?: boolean | null
  content?: string | null
  metadata?: Record<string, unknown>
}

export interface WorkspaceGraphNode {
  acgNodeId: string
  nodeType: string
  name: string
  semanticTaskKey?: string | null
  taskId?: string | null
  identityQuality?: WorkspaceIdentityQuality | null
  displayOrder: number
  status?: string | null
  attemptId?: string | null
  artifactCount?: number
  artifactIds?: string[]
}

export interface WorkspaceDiagnostic {
  code: string
  message: string
  severity: 'info' | 'warning'
  details?: Record<string, unknown>
}

export interface MissionWorkspaceProjection {
  mission: WorkspaceMission
  activeRun?: WorkspaceRunSummary | null
  activeGraph?: AcgBlueprint | null
  runs: WorkspaceRunSummary[]
  entries: WorkspaceEntry[]
  graphNodes: WorkspaceGraphNode[]
  diagnostics: WorkspaceDiagnostic[]
}

export interface ArtifactDetail {
  manifestId: string
  artifactId?: string
  missionId?: string
  originRunId?: string
  taskId?: string
  semanticTaskKey?: string
  artifactKey?: string
  acgNodeId?: string
  producerAttemptId?: string
  name?: string
  artifactType?: string
  mediaType: string
  contentRef?: string
  checksum?: string | null
  byteLength?: number
  fragmentCount?: number
  sealed?: boolean
  createdAt?: string
  metadata?: Record<string, unknown>
}

export interface ArtifactFragment {
  fragmentId?: string
  ordinal?: number
  content: string
}

export interface ArtifactContentResponse extends ArtifactDetail {
  content: string
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
  missionId?: string
  lifecyclePhase?: WorkflowProgressPhase | ''
  source?: string
  sources?: string
  recordState?: 'active' | 'archived'
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
  missionId?: string
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
  missionId?: string
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

export interface WorkflowRerunRequest {
  workflowId?: string
  reviewMode?: string
  input?: Record<string, any>
  enabledPluginIds?: string[] | null
  materialRefs?: string[]
  clientRequestId: string
  sourceRunId: string
  rerunReason: 'manual_rerun' | 'current_configuration' | 'retry_after_failure' | 'planning_variant' | 'review_rerun'
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
  missionId?: string
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
  missionId?: string
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
  name?: string
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
  task?: IdentitySemanticTask
  acgNodeId?: string
  identityAttempts?: IdentityAttemptDetail[]
  stepExecutions?: IdentityStepExecution[]
  nodeExecutions?: NodeExecutionRecord[]
}

export interface MissionRecordMutation {
  missionId: string
  recordState: 'active' | 'archived' | 'deleted'
  affectedRunCount: number
  archivedAt?: string | null
  deletedAt?: string | null
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

export interface ModelCapabilitySnapshot {
  provider: string
  model: string
  version?: string | null
  revision?: string | null
  source: 'provider_reported' | 'adapter_declared' | 'runtime_observed' | 'unknown'
  contextWindowTokens?: number | null
  maxOutputTokens?: number | null
  maxTokensField?: string | null
  features?: Record<string, boolean | null>
}

export interface ModelCallUsage {
  callId: string
  stepId?: string | null
  provider?: string | null
  model?: string | null
  createdAt?: string | null
  latencyMs: number
  usage: {
    inputTokens: number
    outputTokens: number
    cacheReadTokens: number
    cacheWriteTokens: number
    reasoningTokens: number
    totalTokens: number
  }
  finishReason?: string | null
  outputPolicy: string
  requestedOutputTokens?: number | null
  effectiveOutputTokens?: number | null
  effectiveReason?: string | null
  outputExhausted: boolean
  contextPressure?: number | null
  callChainId?: string | null
  partIndex?: number | null
}

export interface RunResourceUsage {
  runId: string
  capability?: ModelCapabilitySnapshot | null
  /** 观测到真实调用为 observed；零调用时来自运行时声明的 catalog 提示为 declared */
  capabilitySource?: 'observed' | 'declared' | null
  outputPolicy?: string | null
  usage: {
    inputTokens: number
    outputTokens: number
    cacheReadTokens: number
    cacheWriteTokens: number
    reasoningTokens: number
    totalTokens: number
    callCount: number
    retryCount: number
    latencyMs: number
    cacheHitRatio?: number | null
  }
  contextPressure: {
    current?: number | null
    peak?: number | null
    currentInputTokens?: number | null
    peakInputTokens?: number | null
    contextWindowTokens?: number | null
    source: string
  }
  composition: {
    materialManifestCount: number
    materialFragmentCount: number
    taskCount: number
    completedTaskCount: number
    persistedResultFragmentCount: number
    reducerManifestCount: number
    chapterCount: number
    artifactCount: number
    assemblyComplete: boolean
    taskProgress?: number | null
  }
  scheduler: { activeSlots: number; queueDepth: number; checkpointCount: number; recoveryCount: number }
}

export interface AcgDeliverable {
  stepId: string
  name: string
  status: string
  output: Record<string, any>
  outputRef?: string
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
  runtimeRevision?: number
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
  executionTree?: RunExecutionTree | null
  operational?: RunOperationalState | null
  identityProjection?: IdentityProjectionState
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
    missionId: run.missionId,
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
    completedStepIds: run.completedStepIds || [],
    startedAt: run.startedAt || null,
    updatedAt: run.updatedAt || null,
    runtimeRevision: run.runtimeRevision,
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

const identityStepStatus = (phase: NodeExecutionPhase): StepStatus => ({
  prepared: 'running',
  executed: 'running',
  audited: 'running',
  committed: 'completed',
  waiting_review: 'waiting_review',
  failed: 'failed',
  cancelled: 'cancelled'
}[phase] as StepStatus)

const compareLoopPath = (left: number[], right: number[]) => {
  const length = Math.max(left.length, right.length)
  for (let index = 0; index < length; index += 1) {
    const difference = (left[index] ?? -1) - (right[index] ?? -1)
    if (difference) return difference
  }
  return 0
}

const projectIdentityStepState = (
  base: AcgStepState,
  identityNode: RunExecutionNode | undefined,
  operational: RunOperationalState | null
): AcgStepState => {
  if (!identityNode || !operational) return base
  const attempts = [...identityNode.attempts].sort((left, right) =>
    left.attempt.attemptNumber - right.attempt.attemptNumber
  )
  const attemptNumberById = new Map(attempts.map(item => [item.attempt.attemptId, item.attempt.attemptNumber]))
  const nodeIds = new Set([base.stepId, identityNode.task.taskId, identityNode.acgNodeId].filter(Boolean))
  const nodeExecutions = operational.nodeExecutions
    .filter(item => nodeIds.has(item.stepId))
    .sort((left, right) => {
      const attemptDifference = (attemptNumberById.get(left.attemptId) || 0) - (attemptNumberById.get(right.attemptId) || 0)
      return attemptDifference || compareLoopPath(left.loopPath, right.loopPath)
        || left.executionInstanceId.localeCompare(right.executionInstanceId)
    })
  const latestAttempt = attempts[attempts.length - 1]
  const latestExecution = nodeExecutions[nodeExecutions.length - 1]
  const stepExecutions = attempts.flatMap(item => item.executions || [])
  return {
    ...base,
    status: latestExecution ? identityStepStatus(latestExecution.phase) : base.status,
    attempt: latestAttempt?.attempt.attemptNumber ?? base.attempt,
    retryCount: Math.max(0, attempts.length - 1),
    currentBinding: latestAttempt?.executionBinding || base.currentBinding,
    attempts: attempts.map(item => ({
      attemptId: item.attempt.attemptId,
      attemptNumber: item.attempt.attemptNumber,
      bindingId: item.executionBinding?.bindingId,
      agentName: item.executionBinding?.agentId,
      modelName: item.executionBinding?.modelId,
      status: item.attempt.status === 'succeeded' ? 'completed' : item.attempt.status as StepStatus,
      startedAt: item.attempt.startedAt || undefined,
      endedAt: item.attempt.finishedAt,
      errorSummary: item.attempt.failureReason
    })),
    task: identityNode.task,
    acgNodeId: identityNode.acgNodeId || base.stepId,
    identityAttempts: attempts,
    stepExecutions,
    nodeExecutions,
    errorSummary: latestExecution?.failureCode || latestAttempt?.attempt.failureReason || base.errorSummary
  }
}

export interface WorkflowHistoryConfig {
  runId: string
  title?: string | null
  reviewMode?: string
  enabledPluginIds?: string[]
  input?: Record<string, unknown>
}

export const agentosApi = {
  async createMaterial(content: string, mediaType = 'text/plain'): Promise<ContentManifestSummary> {
    const response = await agentosRequest.post<ContentManifestSummary>('/materials', { content, mediaType })
    return response.data
  },

  async listMissions(
    params: MissionListQuery = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<PageResponse<MissionListItem>> {
    const response = await agentosRequest.get<PageResponse<MissionListItem>>('/missions', {
      params: {
        status: params.status || undefined,
        page: params.page,
        pageSize: params.pageSize
      },
      signal: options.signal
    })
    return response.data
  },

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
        missionId: params.missionId,
        lifecyclePhase: params.lifecyclePhase || undefined,
        source: params.source,
        sources: params.sources,
        recordState: params.recordState,
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
    const response = await agentosRequest.post<WorkflowRun>('/missions', payload)
    return response.data
  },

  async startWorkflowAsync(
    payload: AsyncWorkflowStartRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>('/missions', payload, { signal: options.signal })
    if (!response.data?.runId || !response.data.missionId) {
      throw new WorkflowApiContractError('运行创建响应缺少 runId 或 missionId')
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

  async getMissionWorkspace(
    missionId: string,
    options: { runId?: string; signal?: AbortSignal } = {}
  ): Promise<MissionWorkspaceProjection> {
    const response = await agentosRequest.get<MissionWorkspaceProjection>(
      `/missions/${encodeURIComponent(missionId)}/workspace`,
      {
        params: { runId: options.runId || undefined },
        signal: options.signal
      }
    )
    return response.data
  },

  async getArtifactDetail(
    runId: string,
    contentRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<ArtifactDetail> {
    const response = await agentosRequest.get<ArtifactDetail>(
      `${runPath(runId)}/artifacts/${encodeURIComponent(contentRef)}`,
      { signal: options.signal }
    )
    return response.data
  },

  async getArtifactContent(
    runId: string,
    contentRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<ArtifactContentResponse> {
    const detail = await this.getArtifactDetail(runId, contentRef, options)
    const items: ArtifactFragment[] = []
    let cursor: string | undefined
    do {
      const response = await agentosRequest.get<{
        manifest: ArtifactDetail
        items: ArtifactFragment[]
        nextCursor?: string | null
      }>(`${runPath(runId)}/artifacts/${encodeURIComponent(contentRef)}/fragments`, {
        params: { cursor, pageSize: 200 },
        signal: options.signal
      })
      items.push(...(response.data.items || []))
      cursor = response.data.nextCursor || undefined
    } while (cursor)
    return { ...detail, content: items.map(item => item.content).join('') }
  },

  async downloadArtifact(
    runId: string,
    contentRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<Blob> {
    const response = await agentosRequest.get<Blob>(
      `${runPath(runId)}/artifacts/${encodeURIComponent(contentRef)}/download`,
      { responseType: 'blob', signal: options.signal }
    )
    return response.data
  },

  async getRunResourceUsage(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunResourceUsage> {
    const response = await agentosRequest.get<RunResourceUsage>(`${runPath(runId)}/resource-usage`, { signal: options.signal })
    return response.data
  },

  async rerunWorkflowAsync(
    missionId: string,
    payload: WorkflowRerunRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>(
      `/missions/${encodeURIComponent(missionId)}/runs`,
      payload,
      { signal: options.signal }
    )
    if (!response.data?.runId || response.data.missionId !== missionId) {
      throw new WorkflowApiContractError('重新运行响应缺少有效的同 Mission Run')
    }
    return response.data
  },

  async listRunResourceCalls(
    runId: string,
    params: { stepId?: string; cursor?: string; pageSize?: number } = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<{ runId: string; items: ModelCallUsage[]; nextCursor?: string | null; total: number }> {
    const response = await agentosRequest.get(`${runPath(runId)}/resource-usage/calls`, {
      params: { stepId: params.stepId, cursor: params.cursor, pageSize: params.pageSize || 20 },
      signal: options.signal
    })
    return response.data
  },

  async archiveMission(missionId: string): Promise<MissionRecordMutation> {
    const response = await agentosRequest.post<MissionRecordMutation>(
      `/missions/${encodeURIComponent(missionId)}/archive`, {}
    )
    return response.data
  },

  async restoreMission(missionId: string): Promise<MissionRecordMutation> {
    const response = await agentosRequest.post<MissionRecordMutation>(
      `/missions/${encodeURIComponent(missionId)}/restore`, {}
    )
    return response.data
  },

  async deleteMission(missionId: string): Promise<MissionRecordMutation> {
    const response = await agentosRequest.delete<MissionRecordMutation>(
      `/missions/${encodeURIComponent(missionId)}`
    )
    return response.data
  },

  async getExecutionTree(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunExecutionTree> {
    const response = await agentosRequest.get<RunExecutionTree>(`${runPath(runId)}/execution-tree`, {
      signal: options.signal
    })
    return response.data
  },

  async getIdentityHealth(options: { signal?: AbortSignal } = {}): Promise<IdentityProjectionHealth> {
    const response = await agentosRequest.get<IdentityProjectionHealth>('/identity/health', {
      signal: options.signal
    })
    return response.data
  },

  async listResources(options: { signal?: AbortSignal } = {}): Promise<{ items: RuntimeResourceItem[]; total: number }> {
    const response = await agentosRequest.get<{ items: RuntimeResourceItem[]; total: number }>('/resources', {
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

  async getRunProvenance(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunProvenanceProjection> {
    const response = await agentosRequest.get<RunProvenanceProjection>(`${runPath(runId)}/provenance`, { signal: options.signal })
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

  async cancelWorkflowRun(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>(`${runPath(runId)}/cancel`, {}, { signal: options.signal })
    return response.data
  },

  async getAcgView(runId: string, options: { signal?: AbortSignal; run?: WorkflowRun | Promise<WorkflowRun> } = {}): Promise<AcgView> {
    const coreRequests = [
      options.run || this.getWorkflowRun(runId, options),
      agentosRequest.get<any>(`${runPath(runId)}/graph`, { signal: options.signal }),
      agentosRequest.get<any>(`${runPath(runId)}/provenance`, { signal: options.signal }),
      this.getWorkflowTrace(runId, options)
    ] as const
    const identityRequest = this.getExecutionTree(runId, options)
      .then(executionTree => ({ executionTree, projection: { status: 'available' as const } }))
      .catch((error: unknown) => {
        if (axios.isCancel(error)) throw error
        const status = axios.isAxiosError(error) ? error.response?.status : undefined
        return {
          executionTree: null,
          projection: {
            status: status === 404 ? 'pending' as const : 'unavailable' as const,
            message: status === 404 ? 'Identity 投影同步中' : 'Identity 投影暂时不可用'
          }
        }
      })
    // Run 是主投影，图/血缘/Trace/Identity/输出都是可降级的辅助投影。
    // 某一路暂时失败时仍返回其它已取得的增量数据，避免运行中的节点答案消失。
    const coreResults = await Promise.allSettled(coreRequests)
    const runResult = coreResults[0]
    if (runResult.status === 'rejected') throw runResult.reason
    const run = runResult.value
    const graphResult = coreResults[1]
    const provenanceResult = coreResults[2]
    const traceResult = coreResults[3]
    for (const result of [graphResult, provenanceResult, traceResult]) {
      if (result.status === 'rejected' && axios.isCancel(result.reason)) throw result.reason
    }
    const graph = graphResult.status === 'fulfilled'
      ? graphResult.value.data
      : (run.acgBlueprint || null)
    const provenance = provenanceResult.status === 'fulfilled'
      ? provenanceProjection(provenanceResult.value.data)
      : { schemaVersion: undefined, integrityStatus: 'unknown', productions: [], consumptions: [], interactions: [] }
    const trace: WorkflowTraceExport = traceResult.status === 'fulfilled'
      ? traceResult.value
      : { runId, missionId: run.missionId, workflowId: run.workflowId, domain: run.domain, status: run.status, eventCount: 0, events: [] }
    const identityResult = await identityRequest
    const outputRefs = Object.entries(run.executionState?.outputRefs || {}) as Array<[string, string]>
    const outputResults: PromiseSettledResult<AcgDeliverable>[] = outputRefs.length
      ? await Promise.allSettled(outputRefs.map(async ([stepId, outputRef]) => {
        const response = await agentosRequest.get<{ content: Record<string, any> }>(
          `${runPath(runId)}/outputs/${encodeURIComponent(outputRef)}`,
          { signal: options.signal }
        )
        const step = run.steps.find(item => item.stepId === stepId)
        return { stepId, outputRef, name: step?.name || stepId, status: step?.status || 'completed', output: response.data.content }
      }))
      : []
    const outputByKey = new Map<string, AcgDeliverable>()
    for (const result of outputResults) {
      if (result.status === 'rejected' && axios.isCancel(result.reason)) throw result.reason
      if (result.status !== 'fulfilled') continue
      const item = result.value
      outputByKey.set(`${item.stepId}:${item.outputRef || ''}`, item)
    }
    const outputs = [...outputByKey.values()].sort((left, right) => {
      const leftIndex = run.steps.findIndex(step => step.stepId === left.stepId)
      const rightIndex = run.steps.findIndex(step => step.stepId === right.stepId)
      return (leftIndex < 0 ? Number.MAX_SAFE_INTEGER : leftIndex)
        - (rightIndex < 0 ? Number.MAX_SAFE_INTEGER : rightIndex)
        || left.stepId.localeCompare(right.stepId)
        || (left.outputRef || '').localeCompare(right.outputRef || '')
    })
    const interactions = provenance.interactions
    // 原生直连等新引擎路径只落 prod/cons 投递信封，不生成带 interactionId 的
    // RuntimeInteraction 记录；此时退回按消费投递聚合，否则指标在数据已存在时仍归零。
    const metricSource = interactions.length
      ? interactions
      : provenance.consumptions.filter(item => item.tokensAvailable != null || item.tokensDelivered != null)
    const tokensAvailable = metricSource.reduce((sum, item) => sum + Number(item.tokensAvailable || 0), 0)
    const tokensDelivered = metricSource.reduce((sum, item) => sum + Number(item.tokensDelivered || 0), 0)
    // 运行中每个 outputRef 都是节点级中间结果；只有 Runtime 在终态写入的
    // run.outputRef 才能升级为最终交付，避免把最后一个中间节点冒充报告。
    const finalOutput = run.status === 'completed'
      ? (run.outputRef
        ? outputs.find(item => item.outputRef === run.outputRef)
        : outputs.length === 1 ? outputs[0] : undefined)
      : undefined
    const finalReport = finalOutput ? outputMarkdown(finalOutput.output) : null
    const finalArtifacts = finalOutput ? (() => {
      const item = finalOutput
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
    })() : []
    const executionTree = identityResult.executionTree
    const identityNodesByAcgId = new Map<string, RunExecutionNode>(
      (executionTree?.nodes || []).filter(item => item.acgNodeId).map(item => [item.acgNodeId as string, item] as const)
    )
    const stepStates = run.steps.map(step => projectIdentityStepState({
      stepId: step.stepId,
      status: step.status,
      name: step.name,
      agentName: step.agentName,
      attempt: step.attempt || 0,
      retryCount: step.retryCount || 0,
      currentBinding: run.executionState?.resourceBindings?.[step.stepId] || null,
      outputSummary: step.outputSummary
    }, identityNodesByAcgId.get(step.stepId), executionTree?.operational || null))
    return {
      runId,
      status: run.status,
      engine: run.runtimeEngine || 'acg',
      runtimeRevision: run.runtimeRevision,
      acgBlueprint: graph as AcgBlueprint | null,
      graphVersion: graph?.graphVersion || run.executionState?.graphVersion || null,
      completedStepIds: run.completedStepIds || [],
      activeStepIds: run.activeStepIds || [],
      stepStates,
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
        averageSavingRatio: metricSource.length ? metricSource.reduce((sum, item) => sum + Number(item.savingRatio || 0), 0) / metricSource.length : 0,
        effectiveSavingRatio: tokensAvailable ? (tokensAvailable - tokensDelivered) / tokensAvailable : 0,
        tokensAvailable,
        tokensDelivered,
        tokensSaved: Math.max(0, tokensAvailable - tokensDelivered),
        recoveryCount: trace.events.filter(event => event.eventType === 'run_recovered').length,
        interactionCount: metricSource.length,
        contractViolationCount: trace.events.filter(event => event.eventType === 'contract_violation').length,
        integrityStatus: provenance.integrityStatus || 'invalid'
      },
      executionTree,
      operational: executionTree?.operational || null,
      identityProjection: identityResult.projection
    }
  }
}
