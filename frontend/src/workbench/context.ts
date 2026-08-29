import type { WorkspaceDiagnostic, WorkspaceEntryKind } from '@/services/api/agentos'
import type { WorkbenchContext } from './types'

export interface WorkbenchContextInput {
  missionId: string
  runId?: string | null
  selectedSemanticTaskKey?: string | null
  selectedArtifactId?: string | null
  selectedAcgNodeId?: string | null
  activeEditorId?: string | null
  activeEntryKind?: WorkspaceEntryKind | null
  historicalMode?: boolean
  diagnostics?: readonly WorkspaceDiagnostic[]
}

export const createWorkbenchContext = (input: WorkbenchContextInput): WorkbenchContext => ({
  missionId: input.missionId,
  runId: input.runId || null,
  selectedSemanticTaskKey: input.selectedSemanticTaskKey || null,
  selectedArtifactId: input.selectedArtifactId || null,
  selectedAcgNodeId: input.selectedAcgNodeId || null,
  activeEditorId: input.activeEditorId || null,
  activeEntryKind: input.activeEntryKind || null,
  historicalMode: Boolean(input.historicalMode),
  diagnostics: input.diagnostics || []
})
