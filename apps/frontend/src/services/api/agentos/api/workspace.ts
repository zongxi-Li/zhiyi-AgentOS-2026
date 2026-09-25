import { agentosRequest } from '../client'
import type { MissionWorkspaceProjection } from '../types'

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
  }
})
