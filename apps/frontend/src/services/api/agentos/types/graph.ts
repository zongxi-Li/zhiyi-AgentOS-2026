export interface AcgNode {
  nodeId: string
  nodeType: 'step' | 'agent' | 'skill' | 'memory' | 'evidence' | 'control'
  name?: string
  description?: string
  goal?: string
  agentName?: string
  capability?: string
  controlType?: string
  display?: GraphDisplay
}
export interface AcgEdge {
  edgeId: string
  sourceId: string
  targetId: string
  edgeType: 'dependency' | 'communication' | 'control_flow' | 'execution' | 'write' | 'read' | 'support'
  condition?: string
  activation?: 'inactive' | 'active' | 'terminated' | 'superseded'
  display?: GraphDisplay
}
export interface GraphProjection {
  graphVersion?: number
  taskPlanVersion?: number
  graphId: string
  missionId?: string
  objective?: string
  complexityLevel?: string
  nodes: AcgNode[]
  edges: AcgEdge[]
  display?: GraphDisplay
  workspaceReview?: WorkspaceReviewProjection | null
}

/** Runtime-owned review facts. These never create graph nodes or execution authority. */
export interface WorkspaceReviewProjection {
  schemaVersion: 1
  round: number
  graphVersion: number
  status: 'reading' | 'reviewing' | 'completed' | 'blocked'
  gaps: {
    missingReadCount: number
    missingListingCount: number
    unsupportedEntryCount: number
    missingReads: string[]
    missingListings: string[]
    unsupportedEntries: string[]
  }
  rounds: WorkspaceReviewRound[]
}

export interface WorkspaceReviewRound {
  round: number
  graphVersion: number
  action: string
  reason?: string
  stepIds: string[]
  addedStepIds: string[]
  observationRef?: string | null
  decisionRef?: string | null
  patchRef?: string | null
  traceRefs: string[]
}

export interface GraphDisplay {
  semanticTaskKey?: string
  taskId?: string
  logicalRole?: string
  endpointRole?: string
  agentName?: string
  allowedSkills?: string[]
  dependencyKeys?: string[]
  displayOrder?: number
}

/** Immutable execution versions belonging to one Run, separate from Mission blueprint numbering. */
export interface GraphVersionEntry {
  blueprintId: string | null
  graphId: string
  graphVersion: number
  taskPlanVersion?: number | null
  current: boolean
  createdAt: string | null
  activatedAt?: string | null
  status: 'active' | 'historical'
  predecessorBlueprintId: string | null
  reason: string | null
  patch: {
    patchId: string
    addedNodeIds: string[]
    updatedNodeIds: string[]
    removedNodeIds: string[]
    addedEdgeCount: number
    removedEdgeCount: number
  } | null
  inherited: {
    completedStepIds: string[]
    skippedStepIds: string[]
    attemptIds: string[]
    outputRefs: Record<string, string>
  }
  activationId?: string | null
  handoffId?: string | null
}

export interface GraphVersionHistory {
  runId: string
  graphId: string
  currentBlueprintId: string | null
  currentGraphVersion: number
  items: GraphVersionEntry[]
  proposals?: Array<{
    proposalId: string
    status: 'pending' | 'rejected'
    reason: string | null
    createdAt: string | null
    sourceGraphVersion: number
    targetGraphVersion?: number | null
  }>
}
