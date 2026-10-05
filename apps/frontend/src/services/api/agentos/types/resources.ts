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
/**
 * /resources 查询响应行：仅含资源目录消费方读取的字段（响应收窄）。
 * RuntimeResourceProfile/RuntimeResourceSnapshot 完整形状仍用于注册命令；
 * labels/costMetadata 动态键以后端 typed 键值行表达，详情面板做行化适配。
 */
export interface RuntimeResourceItem {
  profile: RuntimeResourceCatalogProfile
  snapshot: RuntimeResourceCatalogSnapshot
  snapshotVersion: number
}

export interface RuntimeResourceCatalogProfile {
  resourceId: string
  resourceType: RuntimeResourceType
  deploymentTier?: RuntimeDeploymentTier | null
  capabilities: string[]
  domains: string[]
  version: number
  enabled: boolean
  capacity: number
  privacyLevel?: string | null
  dataZone?: string | null
  location?: string | null
  ownerScope?: string | null
  modelIds?: string[] | null
  labels?: Array<{ key: string; value: string }> | null
  costMetadata?: Array<{ key: string; value: number }> | null
  computeCapacity?: {
    cpuCores?: number | null
    memoryMb?: number | null
    gpuType?: string | null
    gpuMemoryMb?: number | null
    bandwidthMbps?: number | null
  } | null
}

export interface RuntimeResourceCatalogSnapshot {
  healthStatus: RuntimeResourceHealth
  utilization?: number | null
  latencyMs?: number | null
  availableSlots?: number | null
  reliability?: number | null
  observedAt?: string | null
}
export interface ResourceRegistrationRequest {
  profile: RuntimeResourceProfile
  snapshot: RuntimeResourceSnapshot
}
/** 资源最近一次 attempt 绑定投影（execution_bindings JOIN attempts 的只读行）。 */
export interface ResourceUsageRecord {
  bindingId: string
  attemptId: string
  runId: string
  taskId: string
  missionId?: string | null
  taskTitle?: string | null
  semanticTaskKey?: string | null
  acgNodeId?: string | null
  agentId: string
  modelId: string
  attemptNumber: number
  attemptStatus: string
  startedAt?: string | null
  finishedAt?: string | null
  boundAt: string
}
/** 资源健康事件历史行（resource_health_events，倒序）。 */
export interface ResourceHealthEvent {
  observedAt?: string | null
  reliability?: number | null
  latencyMs?: number | null
  lastHeartbeat?: string | null
  version: number
}
/** 资源凭据元数据：仅 id 与年龄，秘密材料只在轮换响应中出现一次。 */
export interface ResourceCredentialMetadata {
  resourceId: string
  credentialId: string
  createdAt: string
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
