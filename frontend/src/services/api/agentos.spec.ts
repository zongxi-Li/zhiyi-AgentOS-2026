import { beforeEach, describe, expect, it, vi } from 'vitest'
import { agentosApi, agentosRequest, WorkflowApiContractError } from './agentos'

const run = {
  runId: 'run_1', taskId: 'task_1', workflowId: 'legal.contract_review', domain: 'legal',
  status: 'completed' as const,
  steps: [{
    stepId: 'deliver', name: 'Deliver', agentName: 'legal.drafter', status: 'completed' as const,
    outputRef: 'output:run_1:deliver', outputSummary: 'Contract review ready'
  }],
  completedStepIds: ['deliver'], activeStepIds: [],
  executionState: {
    outputRefs: { deliver: 'output:run_1:deliver' },
    resourceBindings: { deliver: { resourceId: 'legal.drafter' } }
  }
}

describe('AgentOS v2 application API', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('starts a run through the v2 gateway and preserves clientRequestId', async () => {
    const signal = new AbortController().signal
    const post = vi.spyOn(agentosRequest, 'post').mockResolvedValue({ data: run } as never)
    await expect(agentosApi.startWorkflowAsync({
      title: 'Contract review', domain: 'legal', intent: 'contract_review', clientRequestId: 'request_1'
    }, { signal })).resolves.toEqual(run)
    expect(post).toHaveBeenCalledWith('/runs', expect.objectContaining({ clientRequestId: 'request_1' }), { signal })
  })

  it('rejects a successful-looking create response without run identity', async () => {
    vi.spyOn(agentosRequest, 'post').mockResolvedValue({ data: { taskId: 'task_1' } } as never)
    await expect(agentosApi.startWorkflowAsync({
      title: 'Contract review', domain: 'legal', intent: 'contract_review', clientRequestId: 'request_1'
    })).rejects.toBeInstanceOf(WorkflowApiContractError)
  })

  it('derives progress only from the reference-first run projection', async () => {
    const signal = new AbortController().signal
    const get = vi.spyOn(agentosRequest, 'get').mockResolvedValue({ data: run } as never)
    const progress = await agentosApi.getWorkflowProgress('run/1', { signal })
    expect(progress.percent).toBe(100)
    expect(progress.completedSteps).toBe(1)
    expect(get).toHaveBeenCalledWith('/runs/run%2F1', { signal })
  })

  it('preserves task titles in run history summaries', async () => {
    vi.spyOn(agentosRequest, 'get').mockResolvedValue({
      data: { items: [{ ...run, title: 'IC-200智能装配生产线立项实施方案' }], total: 1, page: 1, pageSize: 20 }
    } as never)

    const result = await agentosApi.listWorkflowRuns()

    expect(result.items[0].title).toBe('IC-200智能装配生产线立项实施方案')
  })

  it('dereferences owned outputs and projects real artifacts', async () => {
    const artifact = {
      artifactId: 'artifact_1', type: 'report', title: 'Final result',
      mediaType: 'text/markdown', content: '# Final', structuredData: { riskCount: 2 }
    }
    const get = vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: run } as never)
      .mockResolvedValueOnce({ data: { graphId: 'graph_1', graphVersion: 2, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: { integrityStatus: 'valid', events: [] } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockResolvedValueOnce({ data: { content: { final_answer: '# Final', artifact } } } as never)

    const result = await agentosApi.getAcgView('run_1')

    expect(result.deliverables[0].output.final_answer).toBe('# Final')
    expect(result.finalArtifacts).toEqual([{ ...artifact, stepId: 'deliver' }])
    expect(result.stepStates[0].currentBinding).toEqual({ resourceId: 'legal.drafter' })
    expect(get).toHaveBeenLastCalledWith('/runs/run_1/outputs/output%3Arun_1%3Adeliver', { signal: undefined })
  })

  it('loads inline outputs through the guarded compatibility resource for legacy runs', async () => {
    const legacyRun = {
      ...run,
      steps: [{ ...run.steps[0], outputRef: undefined }],
      executionState: { resourceBindings: {} }
    }
    const get = vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: legacyRun } as never)
      .mockResolvedValueOnce({ data: { graphId: 'graph_legacy', graphVersion: 1, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: { integrityStatus: 'valid', events: [] } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockResolvedValueOnce({
        data: {
          items: [{ stepId: 'deliver', name: 'Deliver', status: 'completed', content: { final_answer: '# Legacy' } }]
        }
      } as never)

    const result = await agentosApi.getAcgView('run_legacy')

    expect(result.stepOutputs).toEqual([
      { stepId: 'deliver', name: 'Deliver', status: 'completed', output: { final_answer: '# Legacy' } }
    ])
    expect(result.finalReport).toBe('# Legacy')
    expect(get).toHaveBeenLastCalledWith('/runs/run_legacy/legacy-outputs', { signal: undefined })
  })

  it('forwards review concurrency fields and does not swallow conflicts', async () => {
    const conflict = { response: { status: 409 } }
    const post = vi.spyOn(agentosRequest, 'post').mockRejectedValue(conflict)
    const payload = {
      stepId: 'human_review', decision: 'approved' as const, operationId: 'operation_1',
      expectedRunUpdatedAt: '2026-07-22T00:00:00Z', expectedStepStatus: 'waiting_review' as const
    }
    await expect(agentosApi.applyWorkflowReview('run_1', payload)).rejects.toBe(conflict)
    expect(post).toHaveBeenCalledWith('/runs/run_1/reviews', payload, { signal: undefined })
  })
})
