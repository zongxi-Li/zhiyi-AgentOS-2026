import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workflowApi } from '@/services/api/workflow'
import { createMissionLaunchAttempt } from './launchAttempt'
import { buildWorkbenchLaunchRequest } from './request'
import { createNativeWorkbenchDraft } from '@/features/acg/workbench'

vi.mock('@/services/api/workflow', () => ({ workflowApi: { startWorkflowAsync: vi.fn(), createMaterial: vi.fn() } }))
const run = { missionId: 'mission', runId: 'run', status: 'pending' } as any
const request = () => buildWorkbenchLaunchRequest({ ...createNativeWorkbenchDraft(), taskGoal: '目标', materialText: '材料' }, [], '', { attachmentIds: ['att'] })

describe('Mission launch attempt snapshots', () => {
  beforeEach(() => { vi.resetAllMocks(); sessionStorage.clear(); vi.mocked(workflowApi.createMaterial).mockResolvedValue({ manifestId: 'sealed' } as any) })
  it('retries the exact prepared request after response loss without recreating Material or changing attachments', async () => {
    vi.mocked(workflowApi.startWorkflowAsync).mockRejectedValueOnce(new Error('lost response')).mockResolvedValueOnce(run)
    const attempt = createMissionLaunchAttempt()
    await expect(attempt.launch(request())).rejects.toThrow('lost response')
    const first = workflowApi.startWorkflowAsync.mock.calls[0][0]
    const result = await attempt.launch(request())
    expect(workflowApi.startWorkflowAsync.mock.calls[1][0]).toEqual(first)
    expect(first).toMatchObject({ materialRefs: ['sealed'], attachmentIds: ['att'] })
    expect(first.input).not.toHaveProperty('materialText')
    expect(result.clientRequestId).toBe(first.clientRequestId)
    expect(workflowApi.createMaterial).toHaveBeenCalledTimes(1)
  })
  it('coalesces concurrent clicks, then gives a subsequent explicit task a fresh identity', async () => {
    let resolve: (value: any) => void
    vi.mocked(workflowApi.startWorkflowAsync).mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValue(run)
    const attempt = createMissionLaunchAttempt()
    const first = attempt.launch(request())
    const second = attempt.launch(request())
    expect(first).toBe(second)
    await vi.waitFor(() => expect(workflowApi.startWorkflowAsync).toHaveBeenCalledTimes(1))
    resolve!(run)
    const accepted = await first
    const next = await attempt.launch(request())
    expect(next.clientRequestId).not.toBe(accepted.clientRequestId)
  })
  it('captures a changed draft as a new operation', async () => {
    vi.mocked(workflowApi.startWorkflowAsync).mockRejectedValueOnce(new Error('lost')).mockResolvedValue(run)
    const attempt = createMissionLaunchAttempt()
    await expect(attempt.launch(request())).rejects.toThrow()
    const next = request(); next.semantics!.objective = '新目标'
    await attempt.launch(next)
    expect(workflowApi.startWorkflowAsync.mock.calls[1][0].clientRequestId).not.toBe(workflowApi.startWorkflowAsync.mock.calls[0][0].clientRequestId)
  })
  it('restores a Conversation request snapshot across instances, freezing context on retry', async () => {
    const cache = { storage: sessionStorage, key: 'retry' }
    vi.mocked(workflowApi.startWorkflowAsync).mockRejectedValueOnce(new Error('lost')).mockResolvedValue(run)
    const first = request(); first.clientRequestId = 'chat-operation'; first.input!.chatContext = ['old']
    await expect(createMissionLaunchAttempt(cache).launch(first)).rejects.toThrow()
    const changed = request(); changed.clientRequestId = 'chat-operation'; changed.input!.chatContext = ['new']
    await createMissionLaunchAttempt(cache).launch(changed)
    expect(workflowApi.startWorkflowAsync.mock.calls[1][0]).toEqual(workflowApi.startWorkflowAsync.mock.calls[0][0])
    expect(workflowApi.createMaterial).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('retry')).toBeNull()
  })
  it('does not repeat a Material side effect with an unknown result', async () => {
    vi.mocked(workflowApi.createMaterial).mockRejectedValue(new Error('material response lost'))
    const attempt = createMissionLaunchAttempt()
    await expect(attempt.launch(request())).rejects.toThrow('material response lost')
    await expect(attempt.launch(request())).rejects.toThrow('Material 创建结果未确认')
    expect(workflowApi.createMaterial).toHaveBeenCalledTimes(1)
    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
  })
  it('keeps prepared Material but changes operation identity after a Composer 409 on explicit retry', async () => {
    const error = { response: { status: 409 } }
    vi.mocked(workflowApi.startWorkflowAsync).mockRejectedValueOnce(error).mockResolvedValue(run)
    const attempt = createMissionLaunchAttempt()
    await expect(attempt.launch(request())).rejects.toBe(error)
    await attempt.launch(request())
    expect(workflowApi.startWorkflowAsync.mock.calls[1][0].clientRequestId).not.toBe(workflowApi.startWorkflowAsync.mock.calls[0][0].clientRequestId)
    expect(workflowApi.createMaterial).toHaveBeenCalledTimes(1)
  })
  it('does not perform preparation for an already aborted operation', async () => {
    const controller = new AbortController(); controller.abort()
    await expect(createMissionLaunchAttempt().launch(request(), { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
    expect(workflowApi.createMaterial).not.toHaveBeenCalled()
    expect(workflowApi.startWorkflowAsync).not.toHaveBeenCalled()
  })
})
