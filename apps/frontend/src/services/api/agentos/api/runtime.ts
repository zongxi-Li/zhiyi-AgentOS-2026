import { agentosRequest } from '../client'
import type { IdentityProjectionHealth, ModelCallUsage, ResourceRegistrationRequest, RunContextPacksResponse, RunExecutionTree, RunProvenanceProjection, RunResourceUsage, RuntimeResourceItem } from '../types'
import { runPath } from '../paths'

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
      signal: options.signal
    })
    return response.data
  },

  async registerResource(payload: ResourceRegistrationRequest): Promise<{ resourceId: string }> {
    const response = await agentosRequest.post<{ resourceId: string }>('/resources/register', payload)
    return response.data
  },

  async getRunProvenance(runId: string, options: { signal?: AbortSignal } = {}): Promise<RunProvenanceProjection> {
    const response = await agentosRequest.get<RunProvenanceProjection>(`${runPath(runId)}/provenance`, { signal: options.signal })
    return response.data
  }
})
