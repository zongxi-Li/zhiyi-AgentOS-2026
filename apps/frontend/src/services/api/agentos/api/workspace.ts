import { agentosRequest } from '../client'
import type { MissionWorkspaceProjection, WorkspaceFileListing } from '../types'

export const createWorkspaceApi = () => ({
  async getMissionWorkspace(
    missionId: string,
    options: { runId?: string; signal?: AbortSignal } = {}
  ): Promise<MissionWorkspaceProjection> {
    const response = await agentosRequest.get<MissionWorkspaceProjection>(
      `/missions/${encodeURIComponent(missionId)}/workspace`,
      {
        params: { runId: options.runId || undefined },
        signal: options.signal
      }
    )
    return response.data
  },

  async listWorkspaceFiles(
    missionId: string,
    path = '.',
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkspaceFileListing> {
    const response = await agentosRequest.get<WorkspaceFileListing>(
      `/missions/${encodeURIComponent(missionId)}/workspace/files`,
      { params: { path, maxEntries: 1000 }, signal: options.signal }
    )
    return response.data
  }
})
