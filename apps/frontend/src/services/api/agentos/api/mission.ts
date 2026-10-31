import { agentosRequest } from '../client'
import type { AsyncWorkflowStartRequest, ContentManifestSummary, InputAttachment, MissionListItem, MissionListQuery, MissionRecordMutation, PageResponse, WorkflowRun, WorkflowStartRequest } from '../types'
import { WorkflowApiContractError } from '../types'
import type { MissionSemanticEditRequest, MissionSemanticResult } from '../types'

export const createMissionApi = () => ({
  async reconcileMissionLaunch(payload: AsyncWorkflowStartRequest, options: { signal?: AbortSignal } = {}): Promise<MissionLaunchReconciliation> {
    return (await agentosRequest.post<MissionLaunchReconciliation>('/mission-launches/reconcile', payload, options)).data
  },
  async getRunRevision(missionId: string, runId: string): Promise<MissionRunRevision> {
    return (await agentosRequest.get<MissionRunRevision>(revisionPath(missionId, runId))).data
  },
  async decideRunRevision(missionId: string, runId: string, payload: MissionRunRevisionDecision): Promise<MissionRunRevisionReceipt> {
    return (await agentosRequest.post<MissionRunRevisionReceipt>(revisionPath(missionId, runId), payload)).data
  },
  async applyRunRevision(missionId: string, runId: string, operationId: string): Promise<{ status: string; runId: string }> {
    return (await agentosRequest.post<{ status: string; runId: string }>(`${revisionPath(missionId, runId)}/${encodeURIComponent(operationId)}/apply`, {})).data
  },
  async editMissionSemantics(missionId: string, payload: MissionSemanticEditRequest): Promise<MissionSemanticResult> {
    const response = await agentosRequest.post<MissionSemanticResult>(`/missions/${encodeURIComponent(missionId)}/semantics`, payload)
    return response.data
  },
  async createMaterial(content: string, mediaType = 'text/plain'): Promise<ContentManifestSummary> {
    const response = await agentosRequest.post<ContentManifestSummary>('/materials', { content, mediaType })
    return response.data
  },

  async uploadAttachment(
    file: File,
    options: { signal?: AbortSignal; onProgress?: (percent: number) => void } = {}
  ): Promise<InputAttachment> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await agentosRequest.post<InputAttachment>('/attachments', formData, {
      signal: options.signal,
      onUploadProgress: event => {
        if (event.total && options.onProgress) {
          options.onProgress(Math.min(100, Math.round(event.loaded * 100 / event.total)))
        }
      }
    })
    return response.data
  },

  async getAttachment(attachmentId: string): Promise<InputAttachment> {
    const response = await agentosRequest.get<InputAttachment>(
      `/attachments/${encodeURIComponent(attachmentId)}`
    )
    return response.data
  },

  async deleteAttachment(attachmentId: string): Promise<void> {
    await agentosRequest.delete(`/attachments/${encodeURIComponent(attachmentId)}`)
  },

  async listMissions(
    params: MissionListQuery = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<PageResponse<MissionListItem>> {
    const response = await agentosRequest.get<PageResponse<MissionListItem>>('/missions', {
      timeout: 10000,
      params: {
        status: params.status || undefined,
        page: params.page,
        pageSize: params.pageSize
      },
      signal: options.signal
    })
    return response.data
  },

  async startWorkflow(payload: WorkflowStartRequest): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>('/missions', payload)
    return response.data
  },

  async startWorkflowAsync(
    payload: AsyncWorkflowStartRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<WorkflowRun> {
    const response = await agentosRequest.post<WorkflowRun>('/missions', payload, { signal: options.signal })
    if (!response.data?.runId || !response.data.missionId) {
      throw new WorkflowApiContractError('运行创建响应缺少 runId 或 missionId')
    }
    return response.data
  },

  async archiveMission(missionId: string): Promise<MissionRecordMutation> {
    const response = await agentosRequest.post<MissionRecordMutation>(
      `/missions/${encodeURIComponent(missionId)}/archive`, {}
    )
    return response.data
  },

  async restoreMission(missionId: string): Promise<MissionRecordMutation> {
    const response = await agentosRequest.post<MissionRecordMutation>(
      `/missions/${encodeURIComponent(missionId)}/restore`, {}
    )
    return response.data
  },

  async deleteMission(missionId: string): Promise<MissionRecordMutation> {
    const response = await agentosRequest.delete<MissionRecordMutation>(
      `/missions/${encodeURIComponent(missionId)}`
    )
    return response.data
  }
})

const revisionPath = (missionId: string, runId: string) => `/missions/${encodeURIComponent(missionId)}/runs/${encodeURIComponent(runId)}/revision`
export type MissionLaunchReconciliation =
  | { status: 'NOT_FOUND' }
  | { status: 'CREATING' | 'CONFLICT' | 'REQUIRES_REVIEW'; missionId?: string }
  | { status: 'CREATED'; missionId: string; runId: string; run: WorkflowRun }
export interface MissionRunRevisionDecision {
  operationId: string
  sourceRevision: number
  targetRevision: number
  decision: 'CONTINUE' | 'REQUEST_REPLAN'
}
export interface MissionRunRevisionReceipt extends MissionRunRevisionDecision {
  missionId: string
  runId: string
  actorId: string
  tenantId: string
  createdAt: string
}
export interface MissionRunRevision {
  missionId: string
  runId: string
  status: 'CURRENT' | 'REVISION_CHANGED' | 'LEGACY_UNBOUND'
  sourceRevision: number
  targetRevision: number
  runStatus: string
  impact: 'NOT_ANALYZED'
  decisionStatus?: 'UNDECIDED' | 'DECISION_STALE' | 'CONTINUE_SELECTED' | 'REPLAN_REQUESTED' | 'SUCCESSOR_CREATED'
  successorRunId?: string
  decisions: MissionRunRevisionReceipt[]
}
