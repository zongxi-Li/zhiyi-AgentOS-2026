export interface AcgNode {
  nodeId: string
  nodeType: 'step' | 'agent' | 'skill' | 'memory' | 'evidence' | 'control'
  name?: string
  description?: string
  goal?: string
  agentName?: string
  capability?: string
  controlType?: string
  metadata?: Record<string, any>
}
export interface AcgEdge {
  edgeId: string
  sourceId: string
  targetId: string
  edgeType: 'dependency' | 'communication' | 'control_flow' | 'execution' | 'write' | 'read' | 'support'
  condition?: string
  activation?: 'inactive' | 'active' | 'terminated' | 'superseded'
  metadata?: Record<string, any>
}
export interface AcgBlueprint {
  graphId: string
  missionId?: string
  objective?: string
  complexityLevel?: string
  nodes: AcgNode[]
  edges: AcgEdge[]
  metadata?: Record<string, any>
}
