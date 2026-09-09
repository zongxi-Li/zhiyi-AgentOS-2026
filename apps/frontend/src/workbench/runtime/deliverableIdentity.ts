import type { WorkspaceEntry } from '@/services/api/agentos'

export const RUN_DELIVERABLE_ARTIFACT_KEY = 'final'
export const RUN_DELIVERABLE_ARTIFACT_TYPE = 'run_deliverable'

export const isRunDeliverableEntry = (entry: Pick<WorkspaceEntry, 'artifactKey' | 'artifactType'>) => (
  entry.artifactKey?.trim().toLowerCase() === RUN_DELIVERABLE_ARTIFACT_KEY
  && entry.artifactType?.trim().toLowerCase() === RUN_DELIVERABLE_ARTIFACT_TYPE
)
