import type { StepStatus } from './workflow'

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
export interface ResourceUseQuery {
  resourceId: string
  agentId?: string
  modelId?: string
  acgNodeId?: string
  deploymentTier?: string
}
export interface IdentityAttemptDetail {
  attempt: IdentityAttempt
  resourceUse?: ResourceUseQuery | null
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
}
export interface RunOperationalState {
  package?: CompiledPackageIdentity | null
  lineage: RunLineage
  nodeExecutions: NodeExecutionRecord[]
  controlFrames: Array<Record<string, unknown>>
  contextRefs?: Record<string, string>
  communicationRefs: string[]
  memoryRefs: string[]
  evidenceRefs: string[]
  leaseStatuses: Record<string, string>
  loopIterations: Record<string, number>
  consensusResults: Record<string, Record<string, unknown>>
  debateSessions: Record<string, Record<string, unknown>>
  recoveryOutcome?: Record<string, unknown> | null
}
export interface RunContextPackSummary {
  [key: string]: unknown
  stepId: string
  contextRef: string
  available: boolean
  objective?: string
  stepGoal?: string
  sourceStepIds?: string[]
  evidenceRefs?: string[]
  missingFields?: string[]
  contractStatus?: string
  tokensDelivered?: number
  tokensAvailable?: number
  savingRatio?: number
  fieldCount?: number
  sourceCount?: number
  dataKeys?: string[]
  sourceDataKeys?: string[]
}
export interface RunContextPacksResponse {
  runId: string
  items: RunContextPackSummary[]
  total: number
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
  graph: import('./graph').GraphProjection
  nodes: RunExecutionNode[]
  lineage: RunLineage
  lifecycles: NodeLifecycleQuery[]
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

export interface NodeLifecycleQuery {
  stepId: string
  attemptId: string
  phase: NodeExecutionPhase
  failureCode?: string
  sequence: number
}
