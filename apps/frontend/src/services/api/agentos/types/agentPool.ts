export interface AgentPoolActiveStep {
  runId: string
  missionId: string
  stepId: string
  stepName: string
  status: string
  startedAt?: string | null
}

export interface AgentPoolInstance {
  registration: { registryId: string; instanceId: string; agentId: string; generation: number; resourceId: string; definitionDigest: string; definitionVersion?: string | null }
  resourceId: string
  agentId: string
  agentName: string
  domain: string
  capabilities: string[]
  definitionVersion?: string | null
  host: { runtimeId: string; displayName: string; environment: string; runtimeKind: string; enabled: boolean }
  enabled: boolean
  draining: boolean
  outcomeUnknown: boolean
  health: { healthy: boolean; lastHeartbeat?: string | null }
  capacity: number
  activeSlots: number
  activeSteps: AgentPoolActiveStep[]
}

export interface AgentPoolSnapshot {
  observedAt: string
  instances: AgentPoolInstance[]
  total: number
}
