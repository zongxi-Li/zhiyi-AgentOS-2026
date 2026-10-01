import type { ResourceUseQuery } from './identity'

export type RuntimeResourceType = 'agent' | 'model' | 'embedding' | 'tool' | 'worker' | 'skill' | 'mcp' | string
export type RuntimeResourceHealth = 'unknown' | 'online' | 'degraded' | 'offline' | string
export type RuntimeDeploymentTier = 'local' | 'terminal' | 'edge' | 'cloud' | string
export interface RuntimeResourceEndpoint {
  protocol: 'local' | 'http' | 'https' | 'grpc' | string
  address: string
}
export interface RuntimeComputeCapacity {
  cpuCores: number
  memoryMb: number
  gpuType?: string | null
  gpuMemoryMb: number
  bandwidthMbps: number
}
export interface RuntimeResourceProfile {
  resourceId: string
  resourceType: RuntimeResourceType
  deploymentTier?: RuntimeDeploymentTier | null
  capabilities: string[]
  domains: string[]
  labels: Record<string, string>
  location?: string | null
  dataZone?: string | null
  costMetadata: Record<string, number>
  capacity: number
  ownerScope?: string | null
  privacyLevel?: string | null
  executionEndpoint?: RuntimeResourceEndpoint | null
  computeCapacity?: RuntimeComputeCapacity
  modelIds?: string[]
  enabled: boolean
  metadata: Record<string, unknown>
  version: number
}
export interface RuntimeResourceSnapshot {
  resourceId: string
  observedAt: string
  availableSlots: number
  utilization: number
  healthStatus: RuntimeResourceHealth
  reliability?: number | null
  latencyMs?: number | null
  metrics: Record<string, number>
}
export interface RuntimeResourceItem {
  profile: RuntimeResourceProfile
  snapshot: RuntimeResourceSnapshot
  snapshotVersion: number
}
export interface ResourceRegistrationRequest {
  profile: RuntimeResourceProfile
  snapshot: RuntimeResourceSnapshot
}
export interface ResourceBindingObservation extends ResourceUseQuery {
  attemptId: string
  taskId: string
  semanticTaskKey?: string | null
  attemptNumber: number
  attemptStatus: string
  startedAt?: string | null
  finishedAt?: string | null
  deploymentTier: RuntimeDeploymentTier | null
}
export interface ResourceFailoverObservation {
  eventId: string
  stepId: string | null
  timestamp: string | null
  failedResources: Array<{
    stepId?: string
    resourceId: string
    error?: string | null
  }>
  retryStepIds: string[]
}
export interface ResourceObservation {
  runId: string
  items: RuntimeResourceItem[]
  bindings: ResourceBindingObservation[]
  attemptCount: number
  source: string
  failoverEvents: ResourceFailoverObservation[]
}
