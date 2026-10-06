import { agentosRequest } from '../client'
import type { IdentityProjectionHealth, ModelCallUsage, ResourceCredentialMetadata, ResourceHealthEvent, ResourceRegistrationRequest, ResourceUsageRecord, RunContextPacksResponse, RunExecutionTree, RunProvenanceProjection, RunResourceUsage, RuntimeResourceItem } from '../types'
import { runPath } from '../paths'
import type { NodeCatalogItem, NodeRegistrationRequest, ResourceRegistrationResult } from '../types'

export const createRuntimeApi = () => ({
  async getRunResourceUsage(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunResourceUsage> {
    const response = await agentosRequest.get<RunResourceUsage>(`${runPath(runId)}/resource-usage`, { signal: options.signal })
    return response.data
  },

  async listRunResourceCalls(
    runId: string,
    params: { stepId?: string; cursor?: string; pageSize?: number } = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<{ runId: string; items: ModelCallUsage[]; nextCursor?: string | null; total: number }> {
    const response = await agentosRequest.get(`${runPath(runId)}/resource-usage/calls`, {
      params: { stepId: params.stepId, cursor: params.cursor, pageSize: params.pageSize || 20 },
      signal: options.signal
    })
    return response.data
  },

  async getExecutionTree(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunExecutionTree> {
    const response = await agentosRequest.get<RunExecutionTree>(`${runPath(runId)}/execution-tree`, {
      signal: options.signal
    })
    return response.data
  },

  async listRunContextPacks(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunContextPacksResponse> {
    const response = await agentosRequest.get<RunContextPacksResponse>(`${runPath(runId)}/context-packs`, {
      signal: options.signal
    })
    return response.data
  },

  async getIdentityHealth(options: { signal?: AbortSignal } = {}): Promise<IdentityProjectionHealth> {
    const response = await agentosRequest.get<IdentityProjectionHealth>('/identity/health', {
      signal: options.signal
    })
    return response.data
  },

  async listResources(options: { signal?: AbortSignal } = {}): Promise<{ items: RuntimeResourceItem[]; total: number }> {
    const response = await agentosRequest.get<{ items: RuntimeResourceItem[]; total: number }>('/resources', {
      signal: options.signal, timeout: 15000
    })
    return response.data
  },

  async registerResource(payload: ResourceRegistrationRequest): Promise<ResourceRegistrationResult> {
    const response = await agentosRequest.post<ResourceRegistrationResult>('/resources/register', payload, { timeout: 15000 })
    return response.data
  },

  async listNodes(options: { signal?: AbortSignal } = {}): Promise<{ items: NodeCatalogItem[]; total: number }> {
    const response = await agentosRequest.get('/nodes', { signal: options.signal, timeout: 15000 })
    return response.data
  },

  async registerNode(payload: NodeRegistrationRequest): Promise<ResourceRegistrationResult> {
    const response = await agentosRequest.post('/nodes/register', payload, { timeout: 15000 })
    return response.data
  },

  async listResourceUsage(
    resourceId: string,
    options: { limit?: number; signal?: AbortSignal } = {}
  ): Promise<{ resourceId: string; items: ResourceUsageRecord[]; total: number }> {
    const response = await agentosRequest.get(`/resources/${encodeURIComponent(resourceId)}/usage`, {
      params: { limit: options.limit || 12 },
      signal: options.signal
    })
    return response.data
  },

  async getResourceHealthHistory(
    resourceId: string,
    options: { limit?: number; signal?: AbortSignal } = {}
  ): Promise<{ resourceId: string; items: ResourceHealthEvent[]; total: number }> {
    const response = await agentosRequest.get(`/resources/${encodeURIComponent(resourceId)}/health-history`, {
      params: { limit: options.limit || 40 },
      signal: options.signal
    })
    return response.data
  },

  async getResourceCredential(resourceId: string, options: { signal?: AbortSignal } = {}): Promise<ResourceCredentialMetadata> {
    const response = await agentosRequest.get(`/resources/${encodeURIComponent(resourceId)}/credential`, {
      signal: options.signal
    })
    return response.data
  },

  async setResourceEnabled(resourceId: string, enabled: boolean): Promise<{ resourceId: string; enabled: boolean; agentLedgerSynced: boolean }> {
    const response = await agentosRequest.post(`/resources/${encodeURIComponent(resourceId)}/enabled`, { enabled })
    return response.data
  },

  async rotateResourceCredential(resourceId: string): Promise<{ resourceId: string; credentialId: string; secret: string }> {
    const response = await agentosRequest.post(`/resources/${encodeURIComponent(resourceId)}/credential/rotate`)
    return response.data
  },

  async probeResource(resourceId: string): Promise<{ resourceId: string; healthy: boolean; reliability: number; latencyMs: number | null; lastHeartbeat: string | null }> {
    const response = await agentosRequest.post(`/resources/${encodeURIComponent(resourceId)}/probe`)
    return response.data
  },

  async getRunProvenance(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunProvenanceProjection> {
    const response = await agentosRequest.get<RunProvenanceProjection>(`${runPath(runId)}/provenance`, { signal: options.signal })
    return response.data
  }
})
