import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import { RuntimeObservationAdapter, projectModelOutput, readRuntimeObservation, type RuntimeTraceObservation } from './observation'

const deferred = <T,>() => {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

const run = (runId: string, status: 'succeeded' | 'running' = 'succeeded') => ({
  runId,
  missionId: 'mission_1',
  workflowId: 'workflow_1',
  domain: 'ops',
  status,
  steps: []
})

const trace = (runId: string) => ({
  runId,
  missionId: 'mission_1',
  workflowId: 'workflow_1',
  domain: 'ops',
  status: 'succeeded' as const,
  eventCount: 1,
  events: [{
    eventId: `event_${runId}`,
    runId,
    stepId: 'step_1',
    eventType: 'step_completed',
    observation: runId,
    payload: {},
    createdAt: '2026-08-29T00:00:00Z'
  }]
})

const provenance = (runId: string) => ({ runId, events: [], productions: [], consumptions: [], interactions: [] })

const resourceResponse = { items: [], total: 0 }

describe('RuntimeObservationAdapter', () => {
  beforeEach(() => {
    vi.spyOn(agentosApi, 'listWorkflowReviews').mockImplementation(async runId => ({
      runId,
      items: [],
      total: 0
    }) as any)
    vi.spyOn(agentosApi, 'listRunContextPacks').mockImplementation(async runId => ({
      runId,
      items: [],
      total: 0
    }))
  })

  afterEach(() => vi.restoreAllMocks())

  it('normalizes trace-backed panels without inventing tool duration', async () => {
    vi.spyOn(agentosApi, 'getWorkflowRun').mockResolvedValue(run('run_1') as any)
    vi.spyOn(agentosApi, 'getWorkflowTrace').mockResolvedValue({
      ...trace('run_1'),
      eventCount: 3,
      events: [
        ...trace('run_1').events,
        {
          eventId: 'tool_event', runId: 'run_1', stepId: 'step_1', eventType: 'tool_called',
          payload: { tool: 'search', name: 'search', status: 'succeeded', latencyMs: 42 },
          createdAt: '2026-08-29T00:01:00Z'
        },
        {
          eventId: 'failure_event', runId: 'run_1', stepId: 'step_1', eventType: 'step_failed',
          observation: 'failed', payload: {}, createdAt: '2026-08-29T00:02:00Z'
        },
        {
          eventId: 'contract_event', runId: 'run_1', stepId: 'step_1', eventType: 'contract_violation',
          observation: 'contract warning', payload: {}, createdAt: '2026-08-29T00:03:00Z'
        },
        {
          eventId: 'recovery_event', runId: 'run_1', eventType: 'run_recovered',
          observation: 'recovered', payload: {
            action: 'resource_failover',
            resources: [{ stepId: 'step_1', resourceId: 'edge-01', error: 'edge down' }],
            retryStepIds: ['step_1']
          }, createdAt: '2026-08-29T00:04:00Z'
        }
      ]
    } as any)
    vi.spyOn(agentosApi, 'getRunProvenance').mockResolvedValue({
      ...provenance('run_1'),
      integrityStatus: 'verified',
      productions: [{ eventId: 'production_1', producerStepId: 'step_1', evidenceRefs: ['trace_1', 'artifact_1'] }]
    } as any)
    vi.mocked(agentosApi.listWorkflowReviews).mockResolvedValue({ runId: 'run_1', items: [{}], total: 1 } as any)
    vi.mocked(agentosApi.listRunContextPacks).mockResolvedValue({
      runId: 'run_1',
      items: [{
        stepId: 'step_1',
        contextRef: 'context:run_1:step_1:hash',
        available: true,
        objective: 'objective',
        stepGoal: 'goal',
        sourceStepIds: ['source_1'],
        evidenceRefs: ['evidence_1'],
        missingFields: [],
        contractStatus: 'valid',
        tokensDelivered: 12,
        tokensAvailable: 20,
        savingRatio: 0.4,
        fieldCount: 2,
        sourceCount: 1,
        dataKeys: ['summary'],
        sourceDataKeys: ['source_1']
      }],
      total: 1
    })
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue(resourceResponse as any)
    vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({ nodes: [] } as any)

    const result = await readRuntimeObservation('run_1')

    expect(result.traces).toHaveLength(5)
    expect(result.events.map(item => item.eventType)).toContain('step_completed')
    expect(result.toolCalls[0]).toMatchObject({
      tool: 'search',
      startedAt: '2026-08-29T00:01:00Z',
      latencyMs: 42,
      durationMs: null
    })
    expect(result.problems[0]).toMatchObject({ source: 'trace', targetStepId: 'step_1' })
    expect(result.audit).toMatchObject({
      provenanceStatus: 'verified',
      provenanceRecordCount: 1,
      evidenceCount: 2,
      contractViolationCount: 1,
      recoveryCount: 1,
      reviewCount: 1
    })
    expect(result.lowEntropy).toMatchObject({
      observed: false,
      source: null,
      tokensAvailable: null,
      tokensDelivered: null,
      recoveryCount: 1,
      contractViolationCount: 1
    })
    expect(result.resourceObservation?.failoverEvents).toEqual([{
      eventId: 'recovery_event',
      stepId: null,
      timestamp: '2026-08-29T00:04:00Z',
      failedResources: [{ stepId: 'step_1', resourceId: 'edge-01', error: 'edge down' }],
      retryStepIds: ['step_1']
    }])
    expect(result.contextPacks).toHaveLength(1)
    expect(result.contextPacks?.[0]).toMatchObject({
      stepId: 'step_1',
      contextRef: 'context:run_1:step_1:hash',
      tokensDelivered: 12
    })
  })

  it('restores low-entropy metrics from real provenance records', async () => {
    vi.spyOn(agentosApi, 'getWorkflowRun').mockResolvedValue(run('run_1') as any)
    vi.spyOn(agentosApi, 'getWorkflowTrace').mockResolvedValue(trace('run_1') as any)
    vi.spyOn(agentosApi, 'getRunProvenance').mockResolvedValue({
      ...provenance('run_1'),
      integrityStatus: 'verified',
      interactions: [{
        interactionId: 'interaction_1', eventId: 'event_1', edgeIds: [], producerStepIds: ['step_1'],
        consumerStepId: 'step_2', producerAgentNames: [], consumerAgentName: 'agent', fieldsByProducer: {},
        tokensAvailable: 1000, tokensDelivered: 400, savingRatio: 0.6, evidenceRefs: [], contractStatus: 'valid'
      }, {
        interactionId: 'interaction_2', eventId: 'event_2', edgeIds: [], producerStepIds: ['step_2'],
        consumerStepId: 'step_3', producerAgentNames: [], consumerAgentName: 'agent', fieldsByProducer: {},
        tokensAvailable: 500, tokensDelivered: 250, savingRatio: 0.5, evidenceRefs: [], contractStatus: 'valid'
      }]
    } as any)
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue(resourceResponse as any)
    vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({ nodes: [] } as any)

    const result = await readRuntimeObservation('run_1')

    expect(result.lowEntropy).toMatchObject({
      observed: true,
      source: 'provenance',
      averageSavingRatio: 0.55,
      effectiveSavingRatio: 0.5666666666666667,
      tokensAvailable: 1500,
      tokensDelivered: 650,
      tokensSaved: 850,
      interactionCount: 2,
      integrityStatus: 'verified'
    })
  })

  it('reads low-entropy metrics from ledger-backed provenance events', async () => {
    vi.spyOn(agentosApi, 'getWorkflowRun').mockResolvedValue(run('run_1') as any)
    vi.spyOn(agentosApi, 'getWorkflowTrace').mockResolvedValue(trace('run_1') as any)
    vi.spyOn(agentosApi, 'getRunProvenance').mockResolvedValue({
      ...provenance('run_1'),
      integrityStatus: 'valid',
      events: [
        {
          eventType: 'data_produced',
          payload: { eventId: 'prod_1', producerStepId: 'step_1', fieldNames: ['brief'] }
        },
        {
          eventType: 'data_consumed',
          payload: {
            eventId: 'cons_1',
            consumerStepId: 'step_2',
            producerStepIds: ['step_1'],
            consumedFields: ['brief'],
            tokensAvailable: 14702,
            tokensDelivered: 11352,
            savingRatio: 0.228,
            contractStatus: 'valid'
          }
        }
      ]
    } as any)
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue(resourceResponse as any)
    vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({
      nodes: [],
      lineage: { parentRunId: 'parent_1' },
      lifecycles: [{ stepId: 'step_2', attemptId: 'attempt_1', phase: 'committed', sequence: 0 }]
    } as any)

    const result = await readRuntimeObservation('run_1')

    expect(result.communication).toHaveLength(1)
    expect(result.provenance).toMatchObject({
      integrityStatus: 'valid',
      productions: [{ eventId: 'prod_1' }],
      consumptions: [{ eventId: 'cons_1', consumerStepId: 'step_2' }]
    })
    expect(result.lineage).toEqual({ parentRunId: 'parent_1' })
    expect(result.lifecycles).toEqual([{ stepId: 'step_2', attemptId: 'attempt_1', phase: 'committed', sequence: 0 }])
    expect(result.lowEntropy).toMatchObject({
      observed: true,
      source: 'provenance',
      averageSavingRatio: 0.228,
      tokensAvailable: 14702,
      tokensDelivered: 11352,
      tokensSaved: 3350,
      interactionCount: 1,
      integrityStatus: 'valid'
    })
    expect(result.lowEntropy.effectiveSavingRatio).toBeCloseTo(0.2279, 3)
  })

  it('drops a stale response after a fast Run switch', async () => {
    const run1Trace = deferred<ReturnType<typeof trace>>()
    const getWorkflowRun = vi.spyOn(agentosApi, 'getWorkflowRun').mockImplementation(async runId => run(runId) as any)
    const getWorkflowTrace = vi.spyOn(agentosApi, 'getWorkflowTrace').mockImplementation(async runId => {
      if (runId === 'run_1') return run1Trace.promise as any
      return trace(runId) as any
    })
    vi.spyOn(agentosApi, 'getRunProvenance').mockImplementation(async runId => provenance(runId) as any)
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue(resourceResponse as any)
    vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({ nodes: [] } as any)

    const updates: string[] = []
    const adapter = new RuntimeObservationAdapter()
    adapter.start('run_1', { onUpdate: observation => updates.push(observation.runId) })
    adapter.start('run_2', { onUpdate: observation => updates.push(observation.runId) })

    await vi.waitFor(() => expect(updates).toEqual(['run_2']))
    run1Trace.resolve(trace('run_1'))
    await Promise.resolve()
    await Promise.resolve()

    expect(updates).toEqual(['run_2'])
    expect(getWorkflowRun).toHaveBeenCalledWith('run_2', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(getWorkflowTrace).toHaveBeenCalledWith('run_2', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    adapter.stop()
  })

  it('keeps an in-flight observation across a same-Run projection refresh', async () => {
    const pending = deferred<ReturnType<typeof trace>>()
    vi.spyOn(agentosApi, 'getWorkflowRun').mockResolvedValue(run('run_1') as any)
    const request = vi.spyOn(agentosApi, 'getWorkflowTrace').mockReturnValue(pending.promise as any)
    vi.spyOn(agentosApi, 'getRunProvenance').mockResolvedValue(provenance('run_1') as any)
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue(resourceResponse as any)
    vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({ nodes: [] } as any)
    const firstUpdate = vi.fn()
    const nextUpdate = vi.fn()
    const adapter = new RuntimeObservationAdapter()
    adapter.start('run_1', { onUpdate: firstUpdate })
    const signal = request.mock.calls[0][1]?.signal
    adapter.start('run_1', { onUpdate: nextUpdate })
    expect(request).toHaveBeenCalledTimes(1)
    expect(signal?.aborted).toBe(false)
    expect(request.mock.calls[0][1]?.view).toBe('workspace')
    pending.resolve(trace('run_1'))
    await vi.waitFor(() => expect(nextUpdate).toHaveBeenCalledTimes(1))
    expect(firstUpdate).not.toHaveBeenCalled()
    adapter.start('run_1', { onUpdate: nextUpdate })
    expect(request).toHaveBeenCalledTimes(1)
    adapter.stop()
  })
})

const traceEvent = (eventId: string, payload: Record<string, any>): RuntimeTraceObservation => ({
  eventId,
  runId: 'run_1',
  stepId: null,
  eventType: 'task_status_changed',
  observation: null,
  timestamp: '2026-09-02T00:00:00Z',
  durationMs: null,
  status: String(payload.status || ''),
  payload,
  source: 'trace'
})

describe('projectModelOutput', () => {
  it('renders deterministic facts from real planner events', () => {
    const items = projectModelOutput([
      traceEvent('e1', { planningProgress: true, category: 'planner', kind: 'started' }),
      traceEvent('e2', {
        planningProgress: true, category: 'planner', kind: 'plan_parsed',
        stage: 'planning', status: 'plan_parsed', taskCount: 6, dependencyCount: 8
      }),
      traceEvent('e3', {
        planningProgress: true, category: 'planner', kind: 'graph_compiled',
        nodeCount: 7, edgeCount: 11
      }),
      traceEvent('e4', { planningProgress: true, category: 'planner', kind: 'completed' })
    ])

    expect(items.map(item => item.title)).toEqual([
      '开始规划任务',
      '任务规划完成 · 6 个任务 · 8 条依赖',
      'ACG 编译完成 · 7 个节点 · 11 条边',
      '规划完成'
    ])
    expect(items[items.length - 1].status).toBe('success')
  })

  it('falls back to engineering stage wording for legacy payloads', () => {
    const items = projectModelOutput([
      traceEvent('legacy_1', { planningProgress: true, stage: 'intent_profile', status: 'started' }),
      traceEvent('legacy_2', { planningProgress: true, stage: 'intent_profile', status: 'completed' })
    ])

    expect(items.map(item => item.title)).toEqual(['意图解析开始', '意图解析完成'])
    expect(items.every(item => item.category === 'runtime')).toBe(true)
    expect(items.some(item => item.title.includes('正在理解'))).toBe(false)
  })

  it('replaces a still-running stage start when a retried attempt begins', () => {
    const items = projectModelOutput([
      traceEvent('s1', {
        planningProgress: true, category: 'planner', kind: 'stage_started',
        stage: 'outline', status: 'started', attempt: 1, retryCount: 0
      }),
      traceEvent('r1', {
        planningProgress: true, category: 'planner', kind: 'retry',
        stage: 'outline', status: 'retrying', attempt: 1, retryCount: 1,
        errorCode: 'MODEL_TIMEOUT'
      }),
      traceEvent('s2', {
        planningProgress: true, category: 'planner', kind: 'stage_started',
        stage: 'outline', status: 'started', attempt: 2, retryCount: 1
      }),
      traceEvent('c1', {
        planningProgress: true, category: 'planner', kind: 'stage_completed',
        stage: 'outline', status: 'completed', attempt: 2
      })
    ])

    const starts = items.filter(item => item.kind === 'stage_started')
    expect(starts).toHaveLength(1)
    expect(starts[0].attempt).toBe(2)
    expect(items.map(item => item.kind)).toEqual(['stage_started', 'retry', 'stage_completed'])
    expect(items.find(item => item.kind === 'retry')?.detail).toBe('错误码 MODEL_TIMEOUT')
    expect(items[items.length - 1].status).toBe('success')
  })

  it('never invents numbers when counts are missing and ignores foreign events', () => {
    const items = projectModelOutput([
      traceEvent('plain', { eventType: 'other', observation: 'not a planning event' }),
      traceEvent('parsed', {
        planningProgress: true, category: 'planner', kind: 'plan_parsed', stage: 'planning'
      }),
      traceEvent('failed', {
        planningProgress: true, category: 'planner', kind: 'failed',
        errorCode: 'ACGPlanningError', safeSummary: 'ACGPlanningError during planning'
      })
    ])

    expect(items).toHaveLength(2)
    expect(items[0].title).toBe('任务规划完成')
    expect(items[0].title).not.toMatch(/\d/)
    expect(items[1].status).toBe('failed')
    expect(items[1].title).toBe('规划失败')
  })
})
