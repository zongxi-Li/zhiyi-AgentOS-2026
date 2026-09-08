import { describe, expect, it } from 'vitest'
import type { WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import { projectRunDocument, safeStructuredOutput } from './runDocument'
import type { RuntimeObservation } from './observation'

const trace = (eventId: string, payload: Record<string, unknown>, overrides: Record<string, unknown> = {}) => ({
  eventId,
  runId: 'run_1',
  stepId: (overrides.stepId as string | null) || null,
  eventType: String(overrides.eventType || 'task_status_changed'),
  observation: null,
  timestamp: '2026-09-05T00:00:00Z',
  durationMs: (overrides.durationMs as number | null) || null,
  status: String(payload.status || ''),
  payload,
  source: 'trace' as const
})

const observation = (traces: ReturnType<typeof trace>) => ({
  runId: 'run_1', runStatus: 'running', traces: Array.isArray(traces) ? traces : [traces], events: [], communication: [], toolCalls: [], problems: [],
  audit: {}, provenance: {}, operational: null, recoveryTrace: [], contractViolations: [], scheduleTrace: [], patchRefs: [], lowEntropy: {}, resourceObservation: null, unavailableSources: []
}) as unknown as RuntimeObservation

const mission = { missionId: 'mission_1', userId: 'user_1', goal: '智慧门诊流程优化', description: '基于任务材料形成可执行方案。', metadata: {}, createdAt: '', updatedAt: '', status: 'active' }
const nodes: WorkspaceGraphNode[] = [{ acgNodeId: 'node_capacity', nodeType: 'task', name: '高峰到达率与服务能力计算', semanticTaskKey: 'capacity.analysis', displayOrder: 0 }]
const entries: WorkspaceEntry[] = [{ entryId: 'artifact:capacity', kind: 'artifact', name: 'capacity-analysis.md', group: 'output', displayOrder: 0, artifactKey: 'capacity-analysis', artifactId: 'artifact_1', semanticTaskKey: 'capacity.analysis', mediaType: 'text/markdown' }]

describe('run document projection', () => {
  it('projects one live document into the fixed planning, execution and result sections', () => {
    const model = projectRunDocument({
      runId: 'run_1', mission, graphNodes: nodes, entries,
      runtimeObservation: observation([
        trace('planner-1', { planningProgress: true, category: 'planner', kind: 'stage_started', stage: 'detail', status: 'started' }),
        trace('task-1', { status: 'started', agentName: 'Capacity Analyst' }, { stepId: 'node_capacity', eventType: 'step_started' }),
        trace('tool-1', { status: 'succeeded', name: 'Read Material', latencyMs: 836 }, { stepId: 'node_capacity', eventType: 'tool_called' })
      ])
    })

    const planner = model.symbols.find(item => item.type === 'planner')!
    const acg = model.symbols.find(item => item.type === 'acg')!
    const execution = model.symbols.find(item => item.type === 'execution')!
    const task = execution.children.find(item => item.type === 'task')!
    const result = model.symbols.find(item => item.type === 'result')!
    expect(model.id).toBe('run:run_1:progress')
    expect(model.symbols.map(item => item.type)).toEqual(['planner', 'acg', 'execution', 'result'])
    expect(planner.children.some(item => item.type === 'stage' && item.title === 'Detail')).toBe(true)
    expect(acg.children).toEqual([])
    expect(task.children.map(item => item.type)).toEqual(['agent', 'tool', 'artifact'])
    expect(task.children.find(item => item.type === 'tool')?.title).toBe('Read Material')
    expect(result.children.map(item => item.type)).toEqual(['artifact'])
    expect(model.symbols.some(item => item.type === 'runtime')).toBe(false)
  })

  it('keeps ACG as a leaf outline symbol instead of a card collection', () => {
    const model = projectRunDocument({ runId: 'run_1', mission, graphNodes: nodes, entries, runtimeObservation: observation([
      trace('planner-graph', { planningProgress: true, category: 'planner', kind: 'graph_compiled', nodeCount: 1, edgeCount: 0 })
    ]) })
    const acg = model.symbols.find(item => item.type === 'acg')!
    expect(acg.type).toBe('acg')
    expect(acg.children).toEqual([])
    expect(acg.subtitle).toBe('1 nodes · 0 edges')
  })

  it('keeps an unmaterialized ACG in a waiting state instead of claiming zero nodes', () => {
    const model = projectRunDocument({
      runId: 'run_1',
      mission,
      graphNodes: [],
      entries: [],
      runtimeObservation: observation([
        trace('planner-started', { planningProgress: true, category: 'planner', kind: 'started' })
      ])
    })

    const graph = model.symbols.find(item => item.type === 'acg')!
    expect(graph.subtitle).toBe('Waiting for compilation')
    expect(graph.metrics).toEqual({})
    expect(graph.subtitle).not.toContain('0 nodes')
  })

  it('filters sensitive structured output before the editor receives it', () => {
    const output = safeStructuredOutput(JSON.stringify({ answer: 'safe', reasoning_content: 'SECRET_REASONING_MARKER', nested: { system_prompt: 'SECRET_SYSTEM_PROMPT' } }))
    expect(output).toContain('safe')
    expect(output).not.toContain('SECRET_REASONING_MARKER')
    expect(output).not.toContain('SECRET_SYSTEM_PROMPT')
    expect(safeStructuredOutput('SECRET_CREDENTIAL')).toBeNull()
  })
})
