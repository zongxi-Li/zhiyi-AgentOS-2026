import { beforeEach, describe, expect, it, vi } from 'vitest'
import { agentosApi, agentosRequest, WorkflowApiContractError } from './agentos'

const run = {
  runId: 'run_1', missionId: 'mission_1', workflowId: 'legal.contract_review', domain: 'legal',
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

const executionTree = (nodes: Array<Record<string, unknown>> = [], nodeExecutions: Array<Record<string, unknown>> = []) => ({
  run: { runId: 'run_1', missionId: 'mission_1', blueprintId: 'blueprint_1', status: 'succeeded', graphVersion: 2, metadata: {} },
  blueprint: { blueprintId: 'blueprint_1', missionId: 'mission_1', version: 2, graphId: 'graph_1', graph: {}, metadata: {} },
  nodes,
  operational: {
    package: { packageId: 'package_1', packageVersion: 2, checksum: 'abc', blueprintHash: 'def' },
    lineage: {}, nodeExecutions, controlFrames: [], communicationRefs: [], memoryRefs: [], evidenceRefs: [],
    leaseStatuses: {}, loopIterations: {}, consensusResults: {}, debateSessions: {}, recoveryOutcome: null
  }
})

describe('AgentOS v2 application API', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('starts a run through the v2 gateway and preserves clientRequestId', async () => {
    const signal = new AbortController().signal
    const post = vi.spyOn(agentosRequest, 'post').mockResolvedValue({ data: run } as never)
    await expect(agentosApi.startWorkflowAsync({
      title: 'Contract review', domain: 'legal', intent: 'contract_review', clientRequestId: 'request_1'
    }, { signal })).resolves.toEqual(run)
    expect(post).toHaveBeenCalledWith('/missions', expect.objectContaining({ clientRequestId: 'request_1' }), { signal })
  })

  it('rejects a successful-looking create response without run identity', async () => {
    vi.spyOn(agentosRequest, 'post').mockResolvedValue({ data: { taskId: 'task_1' } } as never)
    await expect(agentosApi.startWorkflowAsync({
      title: 'Contract review', domain: 'legal', intent: 'contract_review', clientRequestId: 'request_1'
    })).rejects.toBeInstanceOf(WorkflowApiContractError)
  })

  it('creates a rerun under the existing Mission identity', async () => {
    const signal = new AbortController().signal
    const rerun = { ...run, runId: 'run_2', missionId: 'mission/1' }
    const post = vi.spyOn(agentosRequest, 'post').mockResolvedValue({ data: rerun } as never)

    await expect(agentosApi.rerunWorkflowAsync('mission/1', {
      workflowId: 'legal.contract_review',
      clientRequestId: 'request_2',
      sourceRunId: 'run_1',
      rerunReason: 'current_configuration'
    }, { signal })).resolves.toEqual(rerun)

    expect(post).toHaveBeenCalledWith(
      '/missions/mission%2F1/runs',
      expect.objectContaining({ sourceRunId: 'run_1', rerunReason: 'current_configuration' }),
      { signal }
    )
  })

  it('derives progress only from the reference-first run projection', async () => {
    const signal = new AbortController().signal
    const get = vi.spyOn(agentosRequest, 'get').mockResolvedValue({ data: run } as never)
    const progress = await agentosApi.getWorkflowProgress('run/1', { signal })
    expect(progress.percent).toBe(100)
    expect(progress.completedSteps).toBe(1)
    expect(get).toHaveBeenCalledWith('/runs/run%2F1', { signal })
  })

  it('loads the protected workbench configuration for a historical Run', async () => {
    const signal = new AbortController().signal
    const get = vi.spyOn(agentosRequest, 'get').mockResolvedValue({
      data: { runId: 'run/1', title: '历史任务', input: { taskGoal: '恢复目标' } }
    } as never)

    await expect(agentosApi.getWorkflowHistoryConfig('run/1', { signal })).resolves.toMatchObject({
      title: '历史任务', input: { taskGoal: '恢复目标' }
    })
    expect(get).toHaveBeenCalledWith('/runs/run%2F1/history-config', { signal })
  })

  it('preserves task titles in run history summaries', async () => {
    vi.spyOn(agentosRequest, 'get').mockResolvedValue({
      data: { items: [{ ...run, title: 'IC-200智能装配生产线立项实施方案' }], total: 1, page: 1, pageSize: 20 }
    } as never)

    const result = await agentosApi.listWorkflowRuns()

    expect(result.items[0].title).toBe('IC-200智能装配生产线立项实施方案')
  })

  it('forwards the complete run history filter contract', async () => {
    const get = vi.spyOn(agentosRequest, 'get').mockResolvedValue({
      data: { items: [], total: 0, page: 2, pageSize: 50 }
    } as never)

    await agentosApi.listWorkflowRuns({
      statuses: 'running,waiting_review', domain: 'legal', workflowId: 'workflow_1',
      missionId: 'mission_1', lifecyclePhase: 'review', source: 'acg', sources: 'acg,chat',
      summary: true, page: 2, pageSize: 50
    })

    expect(get).toHaveBeenCalledWith('/runs', expect.objectContaining({
      params: expect.objectContaining({
        statuses: 'running,waiting_review', domain: 'legal', workflowId: 'workflow_1',
        missionId: 'mission_1', lifecyclePhase: 'review', source: 'acg', sources: 'acg,chat',
        summary: true, page: 2, pageSize: 50
      })
    }))
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
      .mockResolvedValueOnce({ data: executionTree() } as never)
      .mockResolvedValueOnce({ data: { content: { final_answer: '# Final', artifact } } } as never)

    const result = await agentosApi.getAcgView('run_1')

    expect(result.deliverables[0].output.final_answer).toBe('# Final')
    expect(result.finalArtifacts).toEqual([{ ...artifact, stepId: 'deliver' }])
    expect(result.stepStates[0].currentBinding).toEqual({ resourceId: 'legal.drafter' })
    expect(get).toHaveBeenLastCalledWith('/runs/run_1/outputs/output%3Arun_1%3Adeliver', { signal: undefined })
  })

  it('reuses an already loaded Run when projecting the ACG view', async () => {
    const get = vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: { graphId: 'graph_1', graphVersion: 2, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: { integrityStatus: 'valid', events: [] } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockResolvedValueOnce({ data: executionTree() } as never)
      .mockResolvedValueOnce({ data: { content: { final_answer: '# Final' } } } as never)

    await agentosApi.getAcgView('run_1', { run })

    expect(get).not.toHaveBeenCalledWith('/runs/run_1', expect.anything())
    expect(get).toHaveBeenCalledTimes(5)
  })

  it('does not probe removed legacy outputs when a run has no committed output references', async () => {
    const pendingRun = {
      ...run,
      status: 'running' as const,
      steps: [{ ...run.steps[0], outputRef: undefined }],
      executionState: { resourceBindings: {} }
    }
    const get = vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: pendingRun } as never)
      .mockResolvedValueOnce({ data: { graphId: 'graph_1', graphVersion: 1, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: { integrityStatus: 'valid', events: [] } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockResolvedValueOnce({ data: executionTree() } as never)

    const result = await agentosApi.getAcgView('run_1')

    expect(result.stepOutputs).toEqual([])
    expect(result.finalReport).toBeNull()
    expect(get).toHaveBeenCalledTimes(5)
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining('legacy-outputs'), expect.anything())
  })

  it('projects low-entropy metrics and lineage from legacy provenance snapshots', async () => {
    const get = vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: run } as never)
      .mockResolvedValueOnce({ data: { graphId: 'graph_legacy', graphVersion: 1, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: {
        schemaVersion: 2,
        integrityStatus: 'valid',
        productions: [{ eventId: 'prod_000001', producerStepId: 'research', fieldNames: ['findings'] }],
        consumptions: [{ eventId: 'cons_000002', consumerStepId: 'deliver', producerStepIds: ['research'], tokensAvailable: 100, tokensDelivered: 40, savingRatio: 0.6 }],
        interactions: [{ eventId: 'int_000003', interactionId: 'int_000003', consumerStepId: 'deliver', producerStepIds: ['research'], tokensAvailable: 100, tokensDelivered: 40, savingRatio: 0.6 }]
      } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockResolvedValueOnce({ data: executionTree() } as never)
      .mockResolvedValueOnce({ data: { content: { final_answer: '# Final' } } } as never)

    const result = await agentosApi.getAcgView('run_legacy_provenance')

    expect(result.provenance.productions).toHaveLength(1)
    expect(result.provenance.consumptions[0].producerStepIds).toEqual(['research'])
    expect(result.interactions).toHaveLength(1)
    expect(result.lowEntropyMetrics).toMatchObject({
      effectiveSavingRatio: 0.6,
      tokensAvailable: 100,
      tokensDelivered: 40,
      tokensSaved: 60,
      interactionCount: 1,
      integrityStatus: 'valid'
    })
  })

  it('merges Identity nodes and orders loop executions by attempt and loop path', async () => {
    const identityNode = {
      task: { nodeId: 'semantic_task_1', taskId: 'task_1', missionId: 'mission_1', title: 'Deliver', objective: 'Ship result', constraints: [], status: 'running', metadata: {} },
      acgNodeId: 'deliver',
      attempts: [{
        attempt: { attemptId: 'attempt_1', runId: 'run_1', nodeId: 'semantic_task_1', status: 'running', attemptNumber: 1 },
        executionBinding: { bindingId: 'binding_1', attemptId: 'attempt_1', acgNodeId: 'deliver', resourceId: 'resource_1', agentId: 'agent_1', modelId: 'model_1', metadata: {} },
        executions: [{ stepExecutionId: 'step_execution_1', runId: 'run_1', nodeId: 'semantic_task_1', attemptId: 'attempt_1', status: 'running' }]
      }]
    }
    const records = [2, 1].map(iteration => ({
      operationId: `operation_${iteration}`, executionInstanceId: `instance_${iteration}`, runId: 'run_1', stepId: 'deliver',
      attemptId: 'attempt_1', phase: iteration === 2 ? 'committed' : 'audited', artifactRefs: {}, loopPath: [iteration]
    }))
    vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: run } as never)
      .mockResolvedValueOnce({ data: { graphId: 'graph_1', graphVersion: 2, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: { integrityStatus: 'valid', events: [] } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockResolvedValueOnce({ data: executionTree([identityNode], records) } as never)
      .mockResolvedValueOnce({ data: { content: { final_answer: '# Final' } } } as never)

    const result = await agentosApi.getAcgView('run_1')

    expect(result.identityProjection?.status).toBe('available')
    expect(result.stepStates[0].task?.nodeId).toBe('semantic_task_1')
    expect(result.stepStates[0].currentBinding).toMatchObject({ bindingId: 'binding_1', resourceId: 'resource_1' })
    expect(result.stepStates[0].stepExecutions?.[0].stepExecutionId).toBe('step_execution_1')
    expect(result.stepStates[0].nodeExecutions?.map(item => item.loopPath)).toEqual([[1], [2]])
    expect(result.stepStates[0].status).toBe('completed')
  })

  it('keeps the 执行运行时 view available while an Identity projection is pending', async () => {
    vi.spyOn(agentosRequest, 'get')
      .mockResolvedValueOnce({ data: run } as never)
      .mockResolvedValueOnce({ data: { graphId: 'graph_1', graphVersion: 2, nodes: [], edges: [] } } as never)
      .mockResolvedValueOnce({ data: { integrityStatus: 'valid', events: [] } } as never)
      .mockResolvedValueOnce({ data: { events: [] } } as never)
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 404 } })
      .mockResolvedValueOnce({ data: { content: { final_answer: '# Final' } } } as never)

    const result = await agentosApi.getAcgView('run_1')

    expect(result.identityProjection).toMatchObject({ status: 'pending' })
    expect(result.executionTree).toBeNull()
    expect(result.stepStates[0].currentBinding).toEqual({ resourceId: 'legal.drafter' })
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
