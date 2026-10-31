import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workflowApi } from '@/services/api/workflow'
import { WorkflowApiContractError } from '@/services/api/agentos'
import { launchMission } from './launch'
import { buildConversationLaunchRequest } from './request'

vi.mock('@/services/api/workflow', () => ({ workflowApi: { startWorkflowAsync: vi.fn(), startWorkflow: vi.fn() } }))
const request = buildConversationLaunchRequest({ goal: '目标', source: 'chat', conversationId: 'conversation',
  chatContextId: 'chat', chatRoleId: null, messages: [] }, 'operation')
const run = { missionId: 'mission', runId: 'run', status: 'pending', steps: [] } as any

describe('Mission launch service', () => {
  beforeEach(() => vi.resetAllMocks())
  it('submits exactly once, forwards AbortSignal, and returns explicit Mission/Run/operation identity', async () => {
    vi.mocked(workflowApi.startWorkflowAsync).mockResolvedValue(run)
    const signal = new AbortController().signal
    expect(await launchMission(request, { signal })).toEqual({ missionId: 'mission', runId: 'run', run, clientRequestId: 'operation' })
    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledTimes(1)
    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledWith(request, { signal })
    expect(workflowApi.startWorkflow).not.toHaveBeenCalled()
  })
  it.each([undefined, {}, { missionId: 'mission' }, { runId: 'run' }, { missionId: ' ', runId: 'run' }, { missionId: 1, runId: 'run' }])
    ('rejects invalid acceptance without inventing identity: %j', async response => {
      vi.mocked(workflowApi.startWorkflowAsync).mockResolvedValue(response as any)
      await expect(launchMission(request)).rejects.toBeInstanceOf(WorkflowApiContractError)
      expect(workflowApi.startWorkflowAsync).toHaveBeenCalledTimes(1)
    })
  it.each([409, 503])('preserves HTTP %s error without retries or synchronous fallback', async status => {
    const error = { response: { status } }
    vi.mocked(workflowApi.startWorkflowAsync).mockRejectedValue(error)
    await expect(launchMission(request)).rejects.toBe(error)
    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledTimes(1)
    expect(workflowApi.startWorkflow).not.toHaveBeenCalled()
  })
  it('preserves API Contract Error identity', async () => {
    const error = new WorkflowApiContractError('invalid wire')
    vi.mocked(workflowApi.startWorkflowAsync).mockRejectedValue(error)
    await expect(launchMission(request)).rejects.toBe(error)
  })
})
