import { describe, expect, it, vi } from 'vitest'
import { RunRuntimeStore, RuntimeEventClient } from './runtimeEvents'

const event = (sequence: number, eventType: string, nodeId = 'A', attemptId = 'a1', delta = '') => ({
  eventId: `e${sequence}`, eventType, runId: 'run', nodeId, attemptId, sequence,
  timestamp: new Date(sequence * 1000).toISOString(), payload: delta ? { delta } : {}
})

describe('RunRuntimeStore streaming projection', () => {
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
    store.apply({ ...event(5, 'planner.profile.resolved', '', '', ''), payload: { requiredCapabilityCount: 3, expectedArtifactCount: 2 } })
    store.apply({ ...event(6, 'planner.plan.parsed', '', '', ''), payload: { taskCount: 5, dependencyCount: 4 } })
    store.apply({ ...event(7, 'planner.graph.compiled', '', '', ''), payload: { nodeCount: 6, edgeCount: 7 } })

    expect(store.nodes).toEqual({})
    expect(store.planning.status).toBe('RUNNING')
    expect(store.planning.callKey).toBe('outline')
    expect(store.planning.ttftMs).toBe(73)
    expect(store.planning.idleMs).toBe(4)
    expect(store.planning.profile?.requiredCapabilityCount).toBe(3)
    expect(store.planning.plan?.taskCount).toBe(5)
    expect(store.planning.graph?.edgeCount).toBe(7)

    store.apply({ ...event(8, 'planner.completed', '', '', ''), payload: { elapsedMs: 120 } })
    expect(store.planning.status).toBe('COMPLETED')
    expect(store.planning.elapsedMs).toBe(120)
  })
  it('isolates planner events by run id and consumes SSE custom event names', () => {
    class FakeEventSource {
      static latest: FakeEventSource | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      closed = false
      listeners = new Map<string, EventListener>()
      constructor(public readonly url: string) { FakeEventSource.latest = this }
      addEventListener(type: string, listener: EventListener) { this.listeners.set(type, listener) }
      removeEventListener(type: string) { this.listeners.delete(type) }
      close() { this.closed = true }
      dispatch(type: string, payload: Record<string, unknown>) {
        this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(payload) }))
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const store = new RunRuntimeStore('run')
    const client = new RuntimeEventClient(store)
    client.connect()
    const source = FakeEventSource.latest!
    source.dispatch('planner.started', { runId: 'other', eventType: 'planner.started', sequence: 1, payload: {} })
    source.dispatch('planner.started', { runId: 'run', eventType: 'planner.started', sequence: 2, payload: {} })
    expect(store.planning.status).toBe('STARTING')
    client.disconnect()
    expect(source.closed).toBe(true)
    vi.unstubAllGlobals()
  })
})
