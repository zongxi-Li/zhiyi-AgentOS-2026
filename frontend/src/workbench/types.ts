import type { Component } from 'vue'
import type {
  AcgBlueprint,
  WorkspaceDiagnostic,
  WorkspaceEntry,
  WorkspaceEntryKind,
  WorkspaceGraphNode
} from '@/services/api/agentos'

export type WorkbenchSlot = 'activityBar' | 'sidebarViews' | 'editors' | 'inspectors' | 'panels' | 'commands'

export interface WorkbenchContext {
  missionId: string
  runId: string | null
  selectedSemanticTaskKey: string | null
  selectedArtifactId: string | null
  selectedAcgNodeId: string | null
  activeEditorId: string | null
  activeEntryKind: WorkspaceEntryKind | null
  historicalMode: boolean
  diagnostics: readonly WorkspaceDiagnostic[]
}

export interface WorkbenchInspectorContext extends WorkbenchContext {
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
  available: boolean
  graph: AcgBlueprint | null
  runStatus: string | null
}

export interface ActivityBarContribution {
  id: string
  label: string
  icon?: Component
  routeName?: string
}

export interface SidebarViewContribution {
  id: string
  title: string
  component: Component
  isVisible?: (context: WorkbenchContext) => boolean
}

export interface EditorContribution {
  id: string
  entryKinds: readonly WorkspaceEntryKind[]
  component: Component
  canOpen?: (entry: WorkspaceEntry, context: WorkbenchContext) => boolean
  title?: (entry: WorkspaceEntry, context: WorkbenchContext) => string
}

export interface InspectorContribution {
  id: string
  component: Component
  matches: (context: WorkbenchInspectorContext) => boolean
}

export interface PanelContribution {
  id: string
  label: string
  component: Component
  count?: (context: WorkbenchContext) => number | undefined
  isVisible?: (context: WorkbenchContext) => boolean
  getProps?: (context: WorkbenchContext) => Record<string, unknown>
}

export interface CommandContribution {
  id: string
  title: string
  execute: (context: WorkbenchContext) => void | Promise<void>
}

export interface WorkbenchContribution {
  id: string
  activityBar?: readonly ActivityBarContribution[]
  sidebarViews?: readonly SidebarViewContribution[]
  editors?: readonly EditorContribution[]
  inspectors?: readonly InspectorContribution[]
  panels?: readonly PanelContribution[]
  commands?: readonly CommandContribution[]
}
