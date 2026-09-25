import type { AcgBlueprint } from './graph'
import type { WorkflowStatus } from './workflow'
import type { InputAttachment } from './artifacts'

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
  severity: 'info' | 'warning' | 'error'
  details?: Record<string, unknown>
}
export interface MissionWorkspaceProjection {
  mission: WorkspaceMission
  activeRun?: WorkspaceRunSummary | null
  activeGraph?: AcgBlueprint | null
  runs: WorkspaceRunSummary[]
  entries: WorkspaceEntry[]
  graphNodes: WorkspaceGraphNode[]
  inputAttachments?: InputAttachment[]
  diagnostics: WorkspaceDiagnostic[]
}
