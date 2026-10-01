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
