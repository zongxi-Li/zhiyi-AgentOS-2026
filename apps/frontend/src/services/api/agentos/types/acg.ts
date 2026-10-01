import type { StepStatus, TraceEvent, WorkflowStatus } from './workflow'
import type { GraphProjection } from './graph'
import type { IdentityAttemptDetail, IdentityProjectionState, IdentitySemanticTask, IdentityStepExecution, NodeExecutionRecord, RunExecutionTree, RunOperationalState, RuntimeAttemptProjection } from './identity'

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
  resourceUse?: import('./identity').ResourceUseQuery | null
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
  nodeExecutions?: import('./identity').NodeLifecycleQuery[]
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
  artifactKey?: string
  artifactType?: string
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
  acgBlueprint: GraphProjection | null
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
  lineage?: import('./identity').RunLineage | null
  lifecycles?: import('./identity').NodeLifecycleQuery[]
  operational?: RunOperationalState | null
  identityProjection?: IdentityProjectionState
}
