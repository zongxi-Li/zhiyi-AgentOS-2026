import {
  agentosApi,
  type AcgView,
  type AcgBlueprint,
  type AcgNode,
  type AcgEdge,
  type AcgLowEntropyMetrics,
  type AcgDeliverable,
  type AcgFinalArtifact,
  type ProvenanceConsumption,
  type ProvenanceProduction,
  type RuntimeInteraction,
  type AcgStepState,
  type RunExecutionTree,
  type RunOperationalState,
  type RunContextPackSummary,
  type RunContextPacksResponse,
  type NodeExecutionRecord,
  type NodeExecutionPhase,
  type IdentityProjectionHealth,
  type Checkpoint,
  type PageResponse,
  type ReviewRecord,
  type ReviewRequest,
  type WorkflowStartRequest,
  type WorkflowStartResponse,
  type AsyncWorkflowStartRequest,
  type AsyncWorkflowStartResponse,
  type WorkflowRerunRequest,
  type SingleStepRetryRequest,
  type WorkflowProgress,
  type WorkflowProgressPhase,
  type WorkflowRunSummary,
  type ReviewDecision,
  type StepStatus,
  type TraceEvent,
  type WorkflowRun,
  type WorkflowHistoryConfig,
  type WorkflowRunQuery,
  type WorkflowStep,
  type WorkflowStatus,
  type WorkflowTraceExport,
  type RunResourceUsage,
  type ModelCallUsage,
  type ModelCapabilitySnapshot,
  type ContentManifestSummary,
  type InputAttachment,
  type RunMemoryEvent,
  type RunMemoryEventsResponse,
} from './agentos'

export type {
  AcgView,
  AcgBlueprint,
  AcgNode,
  AcgEdge,
  AcgLowEntropyMetrics,
  AcgDeliverable,
  AcgFinalArtifact,
  ProvenanceConsumption,
  ProvenanceProduction,
  RuntimeInteraction,
  AcgStepState,
  RunExecutionTree,
  RunOperationalState,
  RunContextPackSummary,
  RunContextPacksResponse,
  NodeExecutionRecord,
  NodeExecutionPhase,
  IdentityProjectionHealth,
  Checkpoint,
  PageResponse,
  ReviewRecord,
  ReviewRequest,
  WorkflowStartRequest,
  WorkflowStartResponse,
  AsyncWorkflowStartRequest,
  AsyncWorkflowStartResponse,
  WorkflowRerunRequest,
  SingleStepRetryRequest,
  WorkflowProgress,
  WorkflowProgressPhase,
  WorkflowRunSummary,
  RunMemoryEvent,
  RunMemoryEventsResponse,
  ReviewDecision,
  StepStatus,
  TraceEvent,
  WorkflowRun,
  WorkflowHistoryConfig,
  WorkflowRunQuery,
  WorkflowStep,
  WorkflowStatus,
  WorkflowTraceExport,
  RunResourceUsage,
  ModelCallUsage,
  ModelCapabilitySnapshot,
  ContentManifestSummary,
  InputAttachment,
}

export const workflowApi = {
  uploadAttachment(
    file: File,
    options: { signal?: AbortSignal; onProgress?: (percent: number) => void } = {}
  ): Promise<InputAttachment> {
    return agentosApi.uploadAttachment(file, options)
  },

  getAttachment(attachmentId: string): Promise<InputAttachment> {
    return agentosApi.getAttachment(attachmentId)
  },

  deleteAttachment(attachmentId: string): Promise<void> {
    return agentosApi.deleteAttachment(attachmentId)
  },

  createMaterial(content: string, mediaType = 'text/plain'): Promise<ContentManifestSummary> {
    return agentosApi.createMaterial(content, mediaType)
  },

  startWorkflow(payload: WorkflowStartRequest): Promise<WorkflowStartResponse> {
    return agentosApi.startWorkflow(payload)
  },

  startWorkflowAsync(
    payload: AsyncWorkflowStartRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<AsyncWorkflowStartResponse> {
    return agentosApi.startWorkflowAsync(payload, options)
  },

  rerunWorkflowAsync(
    missionId: string,
    payload: WorkflowRerunRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowRun> {
    return agentosApi.rerunWorkflowAsync(missionId, payload, options)
  },

  retryWorkflowStepAsync(
    runId: string,
    stepId: string,
    payload: SingleStepRetryRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowRun> {
    return agentosApi.retryWorkflowStepAsync(runId, stepId, payload, options)
  },

  getWorkflowProgress(
    runId: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowProgress> {
    return agentosApi.getWorkflowProgress(runId, options)
  },

  listRuns(
    params: WorkflowRunQuery = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<PageResponse<WorkflowRunSummary>> {
    return agentosApi.listWorkflowRuns({ page: 1, pageSize: 20, ...params }, options)
  },

  getRun(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowRun> {
    return agentosApi.getWorkflowRun(runId, options)
  },

  listMemoryEvents(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunMemoryEventsResponse> {
    return agentosApi.listMemoryEvents(runId, options)
  },

  getRunResourceUsage(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunResourceUsage> {
    return agentosApi.getRunResourceUsage(runId, options)
  },

  listRunResourceCalls(
    runId: string,
    params: { stepId?: string; cursor?: string; pageSize?: number } = {},
    options: { signal?: AbortSignal } = {}
  ) {
    return agentosApi.listRunResourceCalls(runId, params, options)
  },

  archiveMission(missionId: string) {
    return agentosApi.archiveMission(missionId)
  },

  restoreMission(missionId: string) {
    return agentosApi.restoreMission(missionId)
  },

  deleteMission(missionId: string) {
    return agentosApi.deleteMission(missionId)
  },

  getExecutionTree(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunExecutionTree> {
    return agentosApi.getExecutionTree(runId, options)
  },

  listRunContextPacks(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunContextPacksResponse> {
    return agentosApi.listRunContextPacks(runId, options)
  },

  getIdentityHealth(options: { signal?: AbortSignal } = {}): Promise<IdentityProjectionHealth> {
    return agentosApi.getIdentityHealth(options)
  },

  getRunHistoryConfig(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowHistoryConfig> {
    return agentosApi.getWorkflowHistoryConfig(runId, options)
  },

  getTrace(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowTraceExport> {
    return agentosApi.getWorkflowTrace(runId, options)
  },

  exportTraceMarkdown(runId: string): Promise<string> {
    return agentosApi.exportWorkflowTraceMarkdown(runId)
  },

  listCheckpoints(runId: string, options: { signal?: AbortSignal } = {}): Promise<PageResponse<Checkpoint> & { runId: string }> {
    return agentosApi.listWorkflowCheckpoints(runId, options)
  },

  listReviews(runId: string, options: { signal?: AbortSignal } = {}): Promise<PageResponse<ReviewRecord> & { runId: string }> {
    return agentosApi.listWorkflowReviews(runId, options)
  },

  submitReview(runId: string, payload: ReviewRequest, options: { signal?: AbortSignal } = {}): Promise<WorkflowRun> {
    return agentosApi.applyWorkflowReview(runId, payload, options)
  },

  cancelRun(runId: string, options: { signal?: AbortSignal } = {}): Promise<WorkflowRun> {
    return agentosApi.cancelWorkflowRun(runId, options)
  },

  getAcgView(runId: string, options: { signal?: AbortSignal; run?: WorkflowRun | Promise<WorkflowRun> } = {}): Promise<AcgView> {
    return agentosApi.getAcgView(runId, options)
  }
}
