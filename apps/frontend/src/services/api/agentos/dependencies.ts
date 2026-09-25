import type { WorkflowRun, WorkflowTraceExport, RunExecutionTree } from './types'

export interface WorkflowApiDependencies {
  getWorkflowRun(runId: string, options?: { signal?: AbortSignal }): Promise<WorkflowRun>
  getWorkflowTrace(runId: string, options?: { signal?: AbortSignal; view?: 'workspace' }): Promise<WorkflowTraceExport>
}

export interface ArtifactApiDependencies {
  downloadArtifact(runId: string, contentRef: string, options?: { signal?: AbortSignal }): Promise<Blob>
}

export interface AcgApiDependencies extends WorkflowApiDependencies {
  getExecutionTree(runId: string, options?: { signal?: AbortSignal }): Promise<RunExecutionTree>
}
