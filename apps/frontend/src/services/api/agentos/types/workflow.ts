import type { GraphProjection } from './graph'

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
export interface MemoryAccessEvent {
  kind: 'memory_access'
  stepId: string | null
  retrievalMode: string | null
  hitRefs: string[]
  budget: number | null
  fallbackReason: string | null
  createdAt: string | null
}
export interface MemoryWriteEvent {
  kind: 'memory_event'
  eventId?: string
  runId?: string
  stepId?: string | null
  commitId?: string
  summary?: string
  evidenceRefs?: string[]
  metrics?: {
    fieldCount?: number
    evidenceCount?: number
    modelInvocationCount?: number
    toolCallCount?: number
  }
  decision?: string
  relations?: Array<{ sourceStepId: string; targetStepId: string }>
  [key: string]: unknown
}
export interface PhaseCapsuleEvent {
  kind: 'phase_capsule'
  phaseId?: string
  capsuleRef?: string
  sourceMemoryRefs?: string[]
  evidenceRefs?: string[]
  tokenCount?: number
  [key: string]: unknown
}
export type RunMemoryEvent = MemoryAccessEvent | MemoryWriteEvent | PhaseCapsuleEvent
export interface RunMemoryEventsResponse {
  runId: string
  items: RunMemoryEvent[]
  total: number
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
  outputs?: Array<{ stepId: string; outputRef: string; summary?: string }>
  review?: { subjectType?: string; subjectId?: string; controlId?: string; stepId?: string; reasonCode?: string; iteration?: number; approvals?: number; quorum?: number; accepted?: boolean; strategy?: string }
  lineage?: { parentRunId?: string; sourceRunId?: string; rerunReason?: string; supersedesRunId?: string; supersededByRunId?: string }
  graphVersion?: number
  acgBlueprint?: GraphProjection | null
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
  attachmentIds?: string[]
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
export interface AsyncWorkflowStartRequest extends WorkflowStartRequest {
  clientRequestId: string
}
export interface WorkflowRerunRequest {
  workflowId?: string
  reviewMode?: string
  input?: Record<string, any>
  enabledPluginIds?: string[] | null
  materialRefs?: string[]
  attachmentIds?: string[]
  clientRequestId: string
  sourceRunId: string
  rerunReason: 'manual_rerun' | 'current_configuration' | 'retry_after_failure' | 'planning_variant' | 'review_rerun'
}
export interface SingleStepRetryRequest {
  clientRequestId: string
  reason?: string
  expectedRuntimeRevision?: number
  mode?: 'successor_run' | 'current_run'
}
export type AsyncWorkflowStartResponse = WorkflowRun
export class WorkflowApiContractError extends Error {
  readonly code = 'INVALID_ASYNC_WORKFLOW_RESPONSE'

  constructor(message = '异步启动响应缺少有效的 run.runId') {
    super(message)
    this.name = 'WorkflowApiContractError'
  }
}
export interface WorkflowHistoryConfig {
  runId: string
  title?: string | null
  reviewMode?: string
  enabledPluginIds?: string[]
  input?: Record<string, unknown>
}
