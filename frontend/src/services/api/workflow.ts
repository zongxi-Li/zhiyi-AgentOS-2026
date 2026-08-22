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
  WorkflowProgress,
  WorkflowProgressPhase,
  WorkflowRunSummary,
  ReviewDecision,
  StepStatus,
  TraceEvent,
  WorkflowRun,
  WorkflowHistoryConfig,
  WorkflowRunQuery,
  WorkflowStep,
  WorkflowStatus,
  WorkflowTraceExport,
}

export const workflowApi = {
  startWorkflow(payload: WorkflowStartRequest): Promise<WorkflowStartResponse> {
    return agentosApi.startWorkflow(payload)
  },

  startWorkflowAsync(
    payload: AsyncWorkflowStartRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<AsyncWorkflowStartResponse> {
    return agentosApi.startWorkflowAsync(payload, options)
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

  getExecutionTree(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunExecutionTree> {
    return agentosApi.getExecutionTree(runId, options)
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

  getAcgView(runId: string, options: { signal?: AbortSignal; run?: WorkflowRun | Promise<WorkflowRun> } = {}): Promise<AcgView> {
    return agentosApi.getAcgView(runId, options)
  }
}
