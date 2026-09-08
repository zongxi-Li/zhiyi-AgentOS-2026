import { describe, expect, it } from 'vitest'
import type { WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation, RuntimeTraceObservation } from './observation'
import { projectRunProgress } from './runProgress'

const traceEvent = (
  eventId: string,
  payload: Record<string, any>,
  overrides: Partial<Pick<RuntimeTraceObservation, 'stepId' | 'eventType' | 'timestamp' | 'durationMs'>> = {}
): RuntimeTraceObservation => ({
  eventId,
  runId: 'run_1',
  stepId: overrides.stepId ?? null,
  eventType: overrides.eventType ?? 'task_status_changed',
  observation: null,
  timestamp: overrides.timestamp ?? '2026-09-02T00:00:00Z',
  durationMs: overrides.durationMs ?? null,
  status: String(payload.status || ''),
  payload,
  source: 'trace'
})

const observation = (traces: RuntimeTraceObservation[]): RuntimeObservation => ({
  runId: 'run_1',
  runStatus: 'running',
  traces,
  events: [],
  communication: [],
  toolCalls: [],
  problems: [],
  audit: {
    provenanceStatus: null,
    provenanceRecordCount: 0,
    evidenceCount: 0,
    contractViolationCount: 0,
    recoveryCount: 0
  },
  provenance: { schemaVersion: null, integrityStatus: null, productions: [], consumptions: [], interactions: [] },
  operational: null,
  recoveryTrace: [],
  contractViolations: [],
  scheduleTrace: [],
  patchRefs: [],
  lowEntropy: {
    observed: false, source: null, averageSavingRatio: null, effectiveSavingRatio: null,
    tokensAvailable: null, tokensDelivered: null, tokensSaved: null, recoveryCount: 0,
    degradationCount: 0, interactionCount: 0, contractViolationCount: 0, integrityStatus: null
  },
  resourceObservation: null,
  unavailableSources: []
})

const graphNodes = [
  { acgNodeId: 'node_a', nodeType: 'task', name: '需求分析', semanticTaskKey: 'requirements.analysis', displayOrder: 1 },
  { acgNodeId: 'node_b', nodeType: 'task', name: '架构设计', semanticTaskKey: 'architecture.design', displayOrder: 2 }
] as unknown as WorkspaceGraphNode[]

describe('projectRunProgress', () => {
  it('aggregates planner internals into one group keeping only deterministic results after completion', () => {
    const timeline = projectRunProgress(observation([
      traceEvent('e1', { planningProgress: true, category: 'planner', kind: 'started' }),
      traceEvent('e2', { planningProgress: true, category: 'planner', kind: 'stage_started', stage: 'outline', status: 'started', timeoutSeconds: 480 }),
      traceEvent('e3', { planningProgress: true, category: 'planner', kind: 'plan_parsed', taskCount: 6, dependencyCount: 8 }),
      traceEvent('e4', { planningProgress: true, category: 'planner', kind: 'graph_compiled', nodeCount: 5, edgeCount: 11 }),
      traceEvent('e5', { planningProgress: true, category: 'planner', kind: 'completed' })
    ]), graphNodes)

    expect(timeline.planner?.status).toBe('success')
    expect(timeline.planner?.results.map(item => item.title)).toEqual(['Task Plan', 'ACG Compile'])
    expect(timeline.planner?.results[0].metrics).toMatchObject({ taskCount: 6, dependencyCount: 8 })
    expect(timeline.planner?.results[1].metrics).toMatchObject({ nodeCount: 5, edgeCount: 11 })
    expect(timeline.planner?.phaseBudgetSeconds).toBe(480)
  })

  it('keeps retried stage starts as one running item and surfaces the retry note', () => {
    const timeline = projectRunProgress(observation([
      traceEvent('e1', { planningProgress: true, category: 'planner', kind: 'started' }),
      traceEvent('e2', { planningProgress: true, category: 'planner', kind: 'stage_started', stage: 'outline', status: 'started', attempt: 1 }),
      traceEvent('e3', { planningProgress: true, category: 'planner', kind: 'retry', stage: 'outline', status: 'retrying', attempt: 1, retryCount: 1, errorCode: 'MODEL_TIMEOUT' }),
      traceEvent('e4', { planningProgress: true, category: 'planner', kind: 'stage_started', stage: 'outline', status: 'started', attempt: 2 })
    ]), graphNodes)

    expect(timeline.planner?.status).toBe('warning')
    expect(timeline.planner?.phaseNotes.join(' ')).toContain('错误码 MODEL_TIMEOUT')
  })

  it('groups step and tool events per graph node with selection keys', () => {
    const timeline = projectRunProgress(observation([
      traceEvent('t1', { status: 'started' }, { stepId: 'node_a', eventType: 'step_started' }),
      traceEvent('t2', { tool: 'contract_reader', name: 'Read File', status: 'succeeded', latencyMs: 821 }, { stepId: 'node_a', eventType: 'tool_called' }),
      traceEvent('t3', { status: 'succeeded' }, { stepId: 'node_a', eventType: 'step_succeeded', durationMs: 18000 }),
      traceEvent('t4', { status: 'started' }, { stepId: 'node_b', eventType: 'step_started' }),
      traceEvent('t5', { errorCode: 'TOOL_TIMEOUT' }, { stepId: 'node_b', eventType: 'step_failed' })
    ]), graphNodes)

    expect(timeline.tasks).toHaveLength(2)
    const analysis = timeline.tasks.find(group => group.graphNodeId === 'node_a')
    const design = timeline.tasks.find(group => group.graphNodeId === 'node_b')
    expect(analysis).toMatchObject({ status: 'success', semanticTaskKey: 'requirements.analysis', durationMs: 18000 })
    expect(analysis?.tools.map(tool => tool.title)).toEqual(['Read File'])
    expect(design).toMatchObject({ status: 'failed', errorCode: 'TOOL_TIMEOUT' })
  })

  it('derives a task duration from start and completion timestamps when no duration is supplied', () => {
    const timeline = projectRunProgress(observation([
      traceEvent('t1', { status: 'started' }, {
        stepId: 'node_a',
        eventType: 'step_started',
        timestamp: '2026-09-02T00:00:01.000Z'
      }),
      traceEvent('t2', { status: 'succeeded' }, {
        stepId: 'node_a',
        eventType: 'step_completed',
        timestamp: '2026-09-02T00:00:02.250Z'
      })
    ]), graphNodes)

    expect(timeline.tasks[0]).toMatchObject({ status: 'success', durationMs: 1250 })
  })

  it('does not turn missing task duration data into zero milliseconds', () => {
    const timeline = projectRunProgress(observation([
      traceEvent('t1', { status: 'started' }, { stepId: 'node_a', eventType: 'step_started' }),
      traceEvent('t2', { status: 'succeeded' }, { stepId: 'node_a', eventType: 'step_completed' })
    ]), graphNodes)

    expect(timeline.tasks[0].durationMs).toBeNull()
  })

  it('returns an empty timeline without inventing planner state for legacy-free runs', () => {
    const timeline = projectRunProgress(observation([]), graphNodes)

    expect(timeline.planner).toBeNull()
    expect(timeline.tasks).toHaveLength(0)
  })
})
