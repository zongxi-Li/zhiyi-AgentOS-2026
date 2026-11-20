import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { RunRuntimeStore, RuntimeEventClient, acquireRunRuntimeStore, releaseRunRuntimeStore, reconcileRunRuntimeStore } from './runtimeEvents'
import { companionRuntimeBridge } from '@/features/companion/runtimeBridge'

const event = (sequence: number, eventType: string, nodeId = 'A', attemptId = 'a1', delta = '') => ({
  eventId: `e${sequence}`, eventType, runId: 'run', nodeId, attemptId, sequence,
  timestamp: new Date(sequence * 1000).toISOString(), payload: delta ? { delta } : {}
})

describe('RunRuntimeStore streaming projection', () => {
  it('reconnects a terminal observation only on a newer formal active Run revision', () => {
    const fetchMock = vi.fn(() => new Promise(() => {}))
    vi.stubGlobal('fetch', fetchMock)
    const store = acquireRunRuntimeStore('run')!
    try {
      reconcileRunRuntimeStore({ runId: 'run', status: 'running', runtimeRevision: 10 })
      store.apply(event(1, 'model.started'))
      store.apply(event(2, 'node.failed'))
      store.apply(event(3, 'run.failed', '', ''))
      reconcileRunRuntimeStore({ runId: 'other', status: 'running', runtimeRevision: 99 })
      reconcileRunRuntimeStore({ runId: 'run', status: 'running', runtimeRevision: 10 })
      expect(store.terminal).toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(1)
      reconcileRunRuntimeStore({ runId: 'run', status: 'retrying', runtimeRevision: 11 })
      expect(store.terminal).toBe(false)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      store.apply({ ...event(4, 'runtime.display.snapshot', '', ''), payload: {
        schemaVersion: 1, events: [event(1, 'model.started'), event(2, 'node.failed')], retiredAttempts: { A: ['a1'] },
      } })
      store.apply(event(5, 'model.started', 'A', 'a2'))
      store.apply(event(6, 'model.output.delta', 'A', 'a1', 'late old output'))
      expect(store.nodes.A.currentAttemptId).toBe('a2')
      expect(store.nodes.A.status).toBe('RUNNING')
      store.apply(event(7, 'run.failed', '', ''))
      reconcileRunRuntimeStore({ runId: 'run', status: 'retrying', runtimeRevision: 11 })
      expect(store.terminal).toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    } finally { releaseRunRuntimeStore('run', store); vi.unstubAllGlobals() }
  })
  it('keeps workspace review diagnostics separate from planning, model output and node attempts', () => {
    const store = new RunRuntimeStore('run')
    const apply = (sequence: number, eventType: string, payload: Record<string, unknown> = {}) => store.apply({
      ...event(sequence, eventType, '', ''), payload,
    })
    apply(1, 'planner.model.started', { stage: 'outline', callKey: 'outline' })
    apply(2, 'planner.model.reasoning.delta', { delta: '核对当前输入' })
    apply(3, 'planner.model.output.delta', { publicText: '保留已生成的规划' })
    apply(4, 'planner.model.completed')
    store.apply(event(5, 'model.started'))
    store.apply(event(6, 'model.reasoning.delta', 'A', 'a1', '保留节点思考'))
    store.apply(event(7, 'model.output.delta', 'A', 'a1', '{"content":"保留节点正文"}'))
    store.apply(event(8, 'model.completed'))
    const baseline = JSON.stringify({ planning: store.planning, nodes: store.nodes, history: store.outputHistory })
    apply(9, 'workspace.review.retry', { stage: 'workspace_review', status: 'retrying', errorCode: 'REVIEW_BUSY' })
    expect(store.workspaceReview).toEqual({ status: 'RETRYING', errorCode: 'REVIEW_BUSY', lastActivityAt: event(9, '').timestamp })
    // Even an unexpected node envelope cannot turn a review diagnostic into a node attempt.
    store.apply({ ...event(10, 'workspace.review.blocked', 'unexpected', 'new'), payload: { errorCode: 'REVIEW_EVIDENCE_MISSING' } })
    expect(store.workspaceReview.status).toBe('BLOCKED')
    expect(store.workspaceReview.errorCode).toBe('REVIEW_EVIDENCE_MISSING')
    expect(JSON.stringify({ planning: store.planning, nodes: store.nodes, history: store.outputHistory })).toBe(baseline)
    apply(11, 'workspace.review.resumed', { stage: 'workspace_review', status: 'resumed' })
    expect(store.workspaceReview).toEqual({ status: 'IDLE', errorCode: null, lastActivityAt: event(11, '').timestamp })
    expect(JSON.stringify({ planning: store.planning, nodes: store.nodes, history: store.outputHistory })).toBe(baseline)
    expect(store.terminal).toBe(false)
    store.dispose()
  })
  it('resets and replays workspace review diagnostics while isolating stale, foreign and terminal events', () => {
    const store = new RunRuntimeStore('run')
    const diagnostic = { ...event(2, 'workspace.review.retry', '', ''), payload: { errorCode: 'REVIEW_BUSY' } }
    store.apply({ ...event(1, 'workspace.review.blocked', '', ''), payload: { errorCode: 'OBSOLETE' } })
    store.apply({ ...event(3, 'runtime.display.snapshot', '', ''), payload: { schemaVersion: 1, events: [diagnostic] } })
    expect(store.workspaceReview).toEqual({ status: 'RETRYING', errorCode: 'REVIEW_BUSY', lastActivityAt: diagnostic.timestamp })
    store.apply({ ...event(4, 'workspace.review.blocked', '', ''), runId: 'other', payload: { errorCode: 'FOREIGN' } })
    store.apply({ ...diagnostic, payload: { errorCode: 'STALE' } })
    expect(store.workspaceReview.errorCode).toBe('REVIEW_BUSY')
    const resumed = { ...event(4, 'workspace.review.resumed', '', ''), payload: { stage: 'workspace_review', status: 'resumed' } }
    store.apply({ ...event(5, 'runtime.display.snapshot', '', ''), payload: { schemaVersion: 1, events: [diagnostic, resumed] } })
    expect(store.workspaceReview).toEqual({ status: 'IDLE', errorCode: null, lastActivityAt: resumed.timestamp })
    store.apply({ ...event(6, 'runtime.display.snapshot', '', ''), payload: { schemaVersion: 1, events: [] } })
    expect(store.workspaceReview).toEqual({ status: 'IDLE', errorCode: null, lastActivityAt: null })
    store.apply(event(7, 'run.completed', '', ''))
    store.apply({ ...event(8, 'workspace.review.retry', '', ''), payload: { errorCode: 'LATE' } })
    expect(store.workspaceReview.status).toBe('IDLE')
    store.dispose()
  })
  it('streams reasoning separately from JSON, archives it by call and isolates runs', () => {
    const store = new RunRuntimeStore('run')
    const apply = (sequence: number, eventType: string, payload: Record<string, unknown>) => store.apply({ ...event(sequence, eventType, '', ''), payload })
    apply(1, 'planner.model.started', { stage: 'outline', callKey: 'outline' })
    apply(2, 'planner.model.reasoning.delta', { delta: '先核对约束，' })
    apply(3, 'planner.model.reasoning.delta', { delta: '再拆分任务。' })
    apply(4, 'planner.model.output.delta', { publicText: '功能性需求规格' })
    apply(5, 'planner.model.completed', {})
    expect(store.planning.reasoningBuffer).toBe('先核对约束，再拆分任务。')
    expect(JSON.parse(store.planning.outputBuffer)).toEqual({ content: '功能性需求规格' })
    store.apply({ ...event(6, 'planner.model.reasoning.delta', '', ''), runId: 'other', payload: { delta: 'other run' } })
    expect(store.planning.reasoningBuffer).not.toContain('other run')
    apply(7, 'planner.stage.retry', { stage: 'outline', callKey: 'outline' })
    expect(store.outputHistory).toMatchObject([{ reasoning: '先核对约束，再拆分任务。', text: '功能性需求规格', state: 'retrying', stage: 'outline' }])
    expect(store.planning.reasoningBuffer).toBe('')
    apply(8, 'planner.model.started', { stage: 'outline', callKey: 'outline' })
    apply(9, 'planner.model.reasoning.delta', { delta: '思'.repeat(70000) + '最新片段' })
    apply(10, 'planner.model.completed', {})
    expect(store.planning.reasoningBuffer).toHaveLength(65536)
    expect(store.planning.reasoningBuffer.endsWith('最新片段')).toBe(true)
    expect(store.planning.reasoningTruncated).toBe(true)
    // A baseline contains public task output; prior ephemeral thoughts are not invented.
    store.apply({ ...event(10, 'runtime.display.snapshot', '', ''), payload: { schemaVersion: 1, events: [] } })
    expect(store.planning.reasoningBuffer).toBe('')
    expect(store.planning.reasoningTruncated).toBe(false)
    store.dispose()
  })
  it('publishes only accepted live envelopes from the shared SSE, never snapshot history or rejected frames', async () => {
    const publish = vi.spyOn(companionRuntimeBridge, 'publishAccepted')
    const frames = [
      { ...event(0, 'node.started'), runId: 'foreign' },
      { ...event(5, 'runtime.display.snapshot'), payload: { schemaVersion: 1, events: [event(4, 'planner.failed')] } },
      event(5, 'planner.failed'), // duplicate watermark
      event(6, 'model.started'),
      event(7, 'model.started', 'A', 'a2'),
      event(8, 'node.failed', 'A', 'a1'), // retired attempt
      { ...event(8.5, 'run.failed') },
      event(9, 'run.completed'), event(10, 'node.failed')
    ]
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode(frames.map(value => `data: ${JSON.stringify(value)}\n\n`).join(''))) }
    })
    const fetch = vi.fn().mockResolvedValue(new Response(stream))
    vi.stubGlobal('fetch', fetch)
    const store = new RunRuntimeStore('run')
    const client = new RuntimeEventClient(store)
    try {
      client.connect()
      await flushPromises()
      expect(store.lastSequence).toBe(9)
      expect(publish.mock.calls.map(([value]) => value.sequence)).toEqual([6, 7, 9])
      expect(fetch).toHaveBeenCalledOnce()
    } finally { client.disconnect(); store.dispose(); publish.mockRestore(); vi.unstubAllGlobals() }
  })

  it('rebaselines after a restart and continues cumulative public text without duplication', () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(99, 'model.output.delta', 'obsolete', 'old', 'stale'))
    const first = { ...event(2, 'model.output.delta'), payload: { publicText: '已输出' } }
    store.apply({ ...event(5, 'runtime.display.snapshot'), payload: {
      schemaVersion: 1, sequence: 5, events: [event(1, 'model.started'), first]
    } })
    expect(store.nodes.obsolete).toBeUndefined()
    expect(store.nodes.A.outputBuffer).toBe(JSON.stringify({ content: '已输出' }))
    store.apply({ ...event(6, 'model.output.delta'), payload: { publicText: '已输出，新片段' } })
    store.apply(event(7, 'node.completed'))
    expect(store.nodes.A.outputBuffer).toBe(JSON.stringify({ content: '已输出，新片段' }))
    expect(store.lastSequence).toBe(7)
    store.dispose()
  })

  it('rejects retired attempts and late frames after Run completion', () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'model.started'))
    store.apply(event(2, 'model.started', 'A', 'a2'))
    store.apply(event(3, 'model.output.delta', 'A', 'a1', 'late'))
    expect(store.nodes.A.currentAttemptId).toBe('a2')
    store.apply(event(4, 'run.completed'))
    store.apply(event(5, 'model.started', 'A', 'a3'))
    expect(store.nodes.A.currentAttemptId).toBe('a2')
    store.dispose()
  })
  it('flushes the final chunk before completion and resets each tool model turn', () => {
    const callbacks: FrameRequestCallback[] = []
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => { callbacks.push(cb); return callbacks.length })
    try {
      const store = new RunRuntimeStore('run')
      store.apply(event(1, 'model.started'))
      store.apply(event(2, 'model.output.delta', 'A', 'a1', '{"answer":"第一轮"}'))
      store.apply(event(3, 'model.completed'))
      expect(store.nodes.A.outputBuffer).toBe('{"answer":"第一轮"}')
      store.apply(event(4, 'model.started'))
      expect(store.nodes.A.outputBuffer).toBe('')
      expect(store.outputHistory).toMatchObject([{ id: 'e1', text: '第一轮', kind: 'node' }])
      store.apply(event(5, 'model.output.delta', 'A', 'a1', '{"answer":"第二轮"}'))
      store.apply(event(6, 'node.completed'))
      callbacks.forEach(callback => callback(0))
      expect(store.nodes.A.outputBuffer).toBe('{"answer":"第二轮"}')
      expect(store.nodes.A.status).toBe('COMPLETED')
    } finally { raf.mockRestore() }
  })
  it('preserves public planning summaries across stages and retries without retaining private text', () => {
    const store = new RunRuntimeStore('run')
    const apply = (sequence: number, eventType: string, payload: Record<string, unknown>) => store.apply({
      ...event(sequence, eventType, '', ''), payload,
    })
    apply(1, 'planner.stage.started', { stage: 'intent_profile', callKey: 'profile' })
    apply(2, 'planner.model.started', { stage: 'intent_profile', callKey: 'profile' })
    apply(3, 'planner.model.output.delta', { delta: '{"reasoning_content":"PRIVATE","primaryGoal":"先确认三个校区的数据边界。"}' })
    apply(4, 'planner.stage.started', { stage: 'decompose', callKey: 'tasks' })
    apply(5, 'planner.model.started', { stage: 'decompose', callKey: 'tasks' })
    apply(6, 'planner.model.output.delta', { delta: '{"decompositionRationale":"先统一数据口径，再设计权限。"}' })
    apply(7, 'planner.stage.retry', { stage: 'decompose', callKey: 'tasks' })
    apply(8, 'planner.model.started', { stage: 'decompose', callKey: 'tasks' })
    expect(store.outputHistory.map(item => item.text)).toEqual(['先确认三个校区的数据边界。', '先统一数据口径，再设计权限。'])
    expect(store.outputHistory.map(item => item.id)).toEqual(['e2', 'e5'])
    expect(store.outputHistory[0].timestamp).toBe(event(2, '').timestamp)
    expect(JSON.stringify(store.outputHistory)).not.toContain('PRIVATE')
    expect(store.planning.outputBuffer).toBe('')
  })
  it('bounds retained explanations and archives a pending frame before the next model turn', () => {
    const callbacks: FrameRequestCallback[] = []
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => { callbacks.push(cb); return callbacks.length })
    try {
      const store = new RunRuntimeStore('run')
      for (let i = 0; i < 40; i++) {
        store.apply(event(i * 2 + 1, 'model.started'))
        store.apply(event(i * 2 + 2, 'model.output.delta', 'A', 'a1', `说明 ${i}：${'内容'.repeat(4500)}`))
      }
      expect(store.outputHistory.length).toBeLessThanOrEqual(32)
      expect(store.outputHistory.reduce((sum, item) => sum + item.text.length, 0)).toBeLessThanOrEqual(262144)
      expect(store.outputHistory[store.outputHistory.length - 1].text).toContain('说明 38')
      callbacks.forEach(callback => callback(0))
      expect(store.nodes.A.outputBuffer).toContain('说明 39')
    } finally { raf.mockRestore() }
  })
  it('replays planner call boundaries, stage labels and retry outcomes from a display snapshot', () => {
    const store = new RunRuntimeStore('run')
    const plannerEvent = (sequence: number, eventType: string, payload: Record<string, unknown>) => ({ ...event(sequence, eventType, '', ''), payload })
    const events = [
      plannerEvent(1, 'planner.model.started', { stage: 'intent_profile', callKey: 'profile' }),
      plannerEvent(2, 'planner.model.output.delta', { publicText: '核对三个校区的边界' }),
      plannerEvent(3, 'planner.model.completed', { elapsedMs: 1200 }),
      plannerEvent(4, 'planner.stage.started', { stage: 'detail', callKey: 'detail:1' }),
      plannerEvent(5, 'planner.model.started', { stage: 'detail', callKey: 'detail:1' }),
      plannerEvent(6, 'planner.model.output.delta', { publicText: '补充验收条件' }),
      plannerEvent(7, 'planner.stage.retry', { stage: 'detail', callKey: 'detail:1' }),
      plannerEvent(8, 'planner.model.started', { stage: 'detail', callKey: 'detail:1' }),
    ]
    store.apply({ ...event(8, 'runtime.display.snapshot', '', ''), payload: { schemaVersion: 1, events } })
    expect(store.outputHistory).toMatchObject([
      { id: 'e1', stage: 'intent_profile', state: 'completed', elapsedMs: 1200, text: '核对三个校区的边界' },
      { id: 'e5', stage: 'detail', state: 'retrying', text: '补充验收条件' },
    ])
    expect(store.planning.elapsedMs).toBeNull()
    // Rebaselining must not duplicate archived process records.
    store.apply({ ...event(8, 'runtime.display.snapshot', '', ''), payload: { schemaVersion: 1, events } })
    expect(store.outputHistory).toHaveLength(2)
    store.dispose()
  })
  it('notifies inline approval consumers without changing the durable Run revision', () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'tool.approval_required'))
    store.apply(event(1, 'tool.approval_required'))
    expect(store.activity.approvalRevision).toBe(1)
    expect(store.activity.events).toHaveLength(1)
    store.apply(event(2, 'tool.approval_resolved'))
    expect(store.activity.approvalRevision).toBe(2)
    expect(store.activity.events).toHaveLength(2)
  })
  it('accepts the authenticated terminal snapshot with sequence zero', () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(0, 'run.completed'))
    expect(store.terminal).toBe(true)
  })
  it('starts a fresh transient-stream cursor after reconnect while rejecting duplicates in that stream', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const store = new RunRuntimeStore('run')
    store.apply(event(100, 'node.started'))
    const client = new RuntimeEventClient(store)
    try {
      client.connect()
      store.apply(event(1, 'model.first_token'))
      store.apply(event(2, 'node.completed'))
      store.apply(event(1, 'node.started'))
      expect(store.nodes.A.status).toBe('COMPLETED')
      expect(store.lastSequence).toBe(2)
    } finally { client.disconnect(); vi.unstubAllGlobals() }
  })
  it.each([401, 403])('does not retry an unauthorized stream (%s)', async status => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status })
    vi.stubGlobal('fetch', fetchMock)
    const client = new RuntimeEventClient(new RunRuntimeStore('run'))
    try {
      client.connect(); await vi.advanceTimersByTimeAsync(5000)
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(vi.getTimerCount()).toBe(0)
    } finally { client.disconnect(); vi.useRealTimers(); vi.unstubAllGlobals() }
  })
  it('reconnects a nonterminal clean EOF and cancels its retry on disconnect', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read: async () => ({ done: true }), cancel: async () => {}, releaseLock: vi.fn() }) } })
    vi.stubGlobal('fetch', fetchMock)
    const client = new RuntimeEventClient(new RunRuntimeStore('run'))
    try {
      client.connect()
      await vi.advanceTimersByTimeAsync(1001)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      client.disconnect()
      await vi.advanceTimersByTimeAsync(3000)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(vi.getTimerCount()).toBe(0)
    } finally { client.disconnect(); vi.useRealTimers(); vi.unstubAllGlobals() }
  })
  it('accumulates deltas and deduplicates sequence', async () => {
    vi.useFakeTimers()
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'node.started')); store.apply(event(2, 'model.first_token'))
    store.apply(event(3, 'model.output.delta', 'A', 'a1', 'A'))
    store.apply(event(3, 'model.output.delta', 'A', 'a1', 'A'))
    store.apply(event(4, 'model.output.delta', 'A', 'a1', 'B'))
    await vi.advanceTimersByTimeAsync(16)
    expect(store.nodes.A.outputBuffer).toBe('AB'); expect(store.nodes.A.phase).toBe('STREAMING')
    store.dispose(); vi.useRealTimers()
  })
  it('combines multiple node deltas without waiting for an animation frame', async () => {
    vi.useFakeTimers()
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1)
    const store = new RunRuntimeStore('run')

    try {
      store.apply(event(1, 'model.output.delta', 'A', 'a1', 'A'))
      store.apply(event(2, 'model.output.delta', 'A', 'a1', 'B'))
      expect(store.nodes.A.outputBuffer).toBe('')

      await vi.advanceTimersByTimeAsync(16)

      expect(store.nodes.A.outputBuffer).toBe('AB')
      expect(raf).not.toHaveBeenCalled()
    } finally {
      store.dispose(); vi.useRealTimers()
      raf.mockRestore()
    }
  })
  it('batches planner text and flushes it before failures and terminal Run events', async () => {
    vi.useFakeTimers()
    const store = new RunRuntimeStore('run')
    try {
      store.apply(event(1, 'planner.model.started', '', ''))
      for (let i = 0; i < 100; i++) store.apply(event(i + 2, 'planner.model.output.delta', '', '', 'x'))
      expect(store.planning.outputBuffer).toBe('')
      store.apply(event(102, 'planner.failed', '', ''))
      expect(store.planning.outputBuffer).toBe('x'.repeat(100))
      expect(store.planning.status).toBe('FAILED')
      store.apply(event(103, 'model.output.delta', 'A', 'a1', 'last'))
      store.apply(event(104, 'run.failed'))
      expect(store.nodes.A.outputBuffer).toBe('last')
      expect(store.terminal).toBe(true)
      expect(vi.getTimerCount()).toBe(0)
    } finally { store.dispose(); vi.useRealTimers() }
  })
  it('isolates nodes and attempts', async () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'model.output.delta', 'A', 'a1', 'OLD'))
    store.apply(event(2, 'model.output.delta', 'B', 'b1', 'B'))
    store.apply(event(3, 'model.output.delta', 'A', 'a2', 'NEW'))
    await new Promise(resolve => setTimeout(resolve, 25))
    expect(store.nodes.A.outputBuffer).toBe('NEW'); expect(store.nodes.B.outputBuffer).toBe('B')
  })
  it('maps lifecycle phases and ignores late events after completion', async () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'node.started')); store.apply(event(2, 'model.started')); store.apply(event(3, 'model.completed')); store.apply(event(4, 'node.completed'))
    expect(store.nodes.A.phase).toBe('COMPLETED'); expect(store.nodes.A.status).toBe('COMPLETED')
    store.apply(event(5, 'model.output.delta', 'A', 'a1', 'late'))
    await new Promise(resolve => setTimeout(resolve, 25))
    expect(store.nodes.A.outputBuffer).toBe('')
  })
  it('projects run-scoped planner lifecycle, timing, and semantic facts without a node', () => {
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'planner.started', '', '', ''))
    store.apply({ ...event(2, 'planner.stage.started', '', '', ''), payload: { stage: 'outline', callKey: 'outline' } })
    store.apply({ ...event(3, 'planner.model.first_token', '', '', ''), payload: { elapsedMs: 73 } })
    store.apply({ ...event(4, 'planner.model.activity', '', '', ''), payload: { elapsedMs: 91, idleMs: 4, receivedChunks: 2, receivedLength: 18 } })
    store.apply({ ...event(5, 'planner.model.output.delta', '', '', ''), payload: { stage: 'outline', callKey: 'outline', delta: '{"tasks":' } })
    store.apply({ ...event(6, 'planner.model.output.delta', '', '', ''), payload: { stage: 'outline', callKey: 'outline', delta: '[]}' } })
    store.apply({ ...event(7, 'planner.profile.resolved', '', '', ''), payload: { requiredCapabilityCount: 3, expectedArtifactCount: 2 } })
    store.apply({ ...event(8, 'planner.plan.parsed', '', '', ''), payload: {
      taskCount: 5, dependencyCount: 4,
      nodes: [{ key: 'understand', title: 'Understand', objective: 'Establish scope', capabilityRequirements: ['analysis'], acceptanceCriteria: ['approved'] }],
      relations: [{ sourceKey: 'understand', targetKey: 'deliver', relationType: 'depends_on' }]
    } })
    store.apply({ ...event(9, 'planner.graph.compiled', '', '', ''), payload: { nodeCount: 6, edgeCount: 7 } })
    store.apply({ ...event(10, 'planner.draft.updated', '', '', ''), payload: {
      stage: 'detail',
      nodes: [{ key: 'understand', title: 'Understand', capabilityId: 'task_understanding', status: 'detailed', rationale: 'Establish scope' }],
      edges: [{ sourceKey: 'understand', targetKey: 'analyze', relationType: 'depends_on' }]
    } })

    expect(store.nodes).toEqual({})
    expect(store.planning.status).toBe('RUNNING')
    expect(store.planning.callKey).toBe('outline')
    expect(store.planning.ttftMs).toBe(73)
    expect(store.planning.idleMs).toBe(4)
    expect(store.planning.outputBuffer).toBe('{"tasks":[]}')
    expect(store.planning.chunkCount).toBe(2)
    expect(store.planning.profile?.requiredCapabilityCount).toBe(3)
    expect(store.planning.plan?.taskCount).toBe(5)
    expect(store.planning.plan?.nodes[0].objective).toBe('Establish scope')
    expect(store.planning.plan?.relations[0].targetKey).toBe('deliver')
    expect(store.planning.graph?.edgeCount).toBe(7)
    expect(store.planning.draft.nodes[0]?.rationale).toBe('Establish scope')
    expect(store.planning.draft.edges).toHaveLength(1)

    store.apply({ ...event(11, 'planner.completed', '', '', ''), payload: { elapsedMs: 120 } })
    expect(store.planning.status).toBe('COMPLETED')
    expect(store.planning.elapsedMs).toBe(120)
  })
  it('consumes SSE custom events without a user bearer token', async () => {
    localStorage.setItem('token', 'runtime-token')
    const encoder = new TextEncoder()
    const reader = {
      read: vi.fn().mockResolvedValueOnce({
        done: false,
        value: encoder.encode('event: planner.started\ndata: {"runId":"run","eventType":"planner.started","sequence":2,"payload":{}}\n\n')
      }).mockResolvedValueOnce({
        done: false,
        value: encoder.encode('event: run.failed\ndata: {"runId":"run","eventType":"run.failed","sequence":3,"payload":{}}\n\n')
      }),
      cancel: vi.fn().mockResolvedValue(undefined),
      releaseLock: vi.fn()
    }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } })
    vi.stubGlobal('fetch', fetchMock)
    const store = new RunRuntimeStore('run')
    const client = new RuntimeEventClient(store)
    client.connect()
    await vi.waitFor(() => expect(store.terminal).toBe(true))
    expect(store.planning.status).toBe('STARTING')
    expect(reader.cancel).toHaveBeenCalledOnce()
    expect(reader.releaseLock).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/agentos/v2/runs/run/events'), expect.objectContaining({
      headers: { Accept: 'text/event-stream' },
      signal: expect.any(AbortSignal)
    }))
    localStorage.removeItem('token')
    vi.unstubAllGlobals()
  })

  it('stops at this Run terminal event without applying later buffered frames', async () => {
    const cancel = vi.fn()
    const frames = [
      { ...event(1, 'run.completed'), runId: 'foreign' },
      event(2, 'planner.started'), event(3, 'run.completed'), event(4, 'planner.failed')
    ].map(value => `data: ${JSON.stringify(value)}\n\n`).join('')
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode(frames)) }, cancel
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream)))
    const store = new RunRuntimeStore('run')
    const client = new RuntimeEventClient(store)
    try {
      client.connect()
      await flushPromises()
      expect(store.terminal).toBe(true)
      expect(store.planning.status).toBe('STARTING')
      expect(store.lastSequence).toBe(3)
      expect(cancel).toHaveBeenCalledOnce()
      expect(stream.locked).toBe(false)
    } finally { client.disconnect(); vi.unstubAllGlobals() }
  })

})
