import { agentosRequest } from '../client'
import type { AsyncWorkflowStartRequest, ContentManifestSummary, InputAttachment, MissionListItem, MissionListQuery, MissionRecordMutation, PageResponse, WorkflowRun, WorkflowStartRequest } from '../types'
import { WorkflowApiContractError } from '../types'

export const createMissionApi = () => ({
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
