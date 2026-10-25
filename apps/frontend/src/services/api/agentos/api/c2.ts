import { agentosRequest } from '../client'

export type FormalAction = 'materialize' | 'activate' | 'handoff' | 'permit' | 'dispatch'
export type FormalCommand = { operationId: string } & (
  | { commitId: string; expectedCommitmentRevision: number }
  | { materializationId: string; expectedGraphId: string; expectedGraphVersion: number }
  | { activationId: string; expectedGraphId: string; expectedGraphVersion: number }
  | { handoffId: string; expectedGraphId: string; expectedGraphVersion: number }
  | { expectedPermitId: string; expectedGraphId: string; expectedGraphVersion: number; expectedRuntimeRevision: number }
)
const paths: Record<FormalAction, string> = {
  materialize: 'graph/materializations', activate: 'graph/activation', handoff: 'graph/handoffs',
  permit: 'graph/permits', dispatch: 'execution/dispatches'
}
export const createC2Api = () => ({
  async submitFormalControl(missionId: string, runId: string, action: FormalAction, command: FormalCommand) {
    const response = await agentosRequest.post<{ operationId: string; status: string; dispatchId?: string }>(
      `/missions/${encodeURIComponent(missionId)}/runs/${encodeURIComponent(runId)}/${paths[action]}`, command)
    return response.data
  }
})
