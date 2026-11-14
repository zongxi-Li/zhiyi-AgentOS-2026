import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { RunRuntimeStore, RuntimeEventClient, acquireRunRuntimeStore, releaseRunRuntimeStore } from './runtimeEvents'

const event = (sequence: number, eventType: string, nodeId = 'A', attemptId = 'a1', delta = '') => ({
  eventId: `e${sequence}`, eventType, runId: 'run', nodeId, attemptId, sequence,
  timestamp: new Date(sequence * 1000).toISOString(), payload: delta ? { delta } : {}
})

describe('RunRuntimeStore streaming projection', () => {
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
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => { cb(0); return 1 })
    const store = new RunRuntimeStore('run')
    store.apply(event(1, 'node.started')); store.apply(event(2, 'model.first_token'))
    store.apply(event(3, 'model.output.delta', 'A', 'a1', 'A'))
    store.apply(event(3, 'model.output.delta', 'A', 'a1', 'A'))
    store.apply(event(4, 'model.output.delta', 'A', 'a1', 'B'))
    expect(store.nodes.A.outputBuffer).toBe('AB'); expect(store.nodes.A.phase).toBe('STREAMING')
    raf.mockRestore()
  })
  it('accumulates multiple node deltas queued in the same animation frame', () => {
    const callbacks: FrameRequestCallback[] = []
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => {
      callbacks.push(cb)
      return callbacks.length
    })
    const store = new RunRuntimeStore('run')

    try {
      store.apply(event(1, 'model.output.delta', 'A', 'a1', 'A'))
      store.apply(event(2, 'model.output.delta', 'A', 'a1', 'B'))
      expect(store.nodes.A.outputBuffer).toBe('')

      callbacks[0]?.(0)

      expect(store.nodes.A.outputBuffer).toBe('AB')
    } finally {
      raf.mockRestore()
    }
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
