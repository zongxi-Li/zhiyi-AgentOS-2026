import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import { RuntimeObservationAdapter, readRuntimeObservation } from './observation'

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
          observation: 'recovered', payload: {}, createdAt: '2026-08-29T00:04:00Z'
        }
      ]
    } as any)
    vi.spyOn(agentosApi, 'getRunProvenance').mockResolvedValue({
      ...provenance('run_1'),
      integrityStatus: 'verified',
      productions: [{ eventId: 'production_1', producerStepId: 'step_1', evidenceRefs: ['trace_1', 'artifact_1'] }]
    } as any)
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
      recoveryCount: 1
    })
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
})
