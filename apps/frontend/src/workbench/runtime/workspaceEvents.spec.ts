import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceProjectionClient } from './workspaceEvents'

const clients: WorkspaceProjectionClient[] = []
const connect = (callback = vi.fn()) => {
  const client = new WorkspaceProjectionClient()
  clients.push(client)
  client.connect('mission/id', callback)
  return { client, callback }
}
const frame = (revision: number, missionId = 'mission/id') => `event: workspace.projection.updated\r\ndata: ${JSON.stringify({
  eventType: 'workspace.projection.updated', schemaVersion: 1, missionId, projectionRevision: revision
})}\r\n\r\n`
afterEach(() => { clients.splice(0).forEach(client => client.disconnect()); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('Mission workspace SSE', () => {
  it('handles split CRLF and rejects foreign identities and malformed revisions', async () => {
    const encoder = new TextEncoder()
    const whole = frame(4) + frame(99, 'foreign') + frame(-1)
    const split = whole.indexOf('\r\n\r\n') + 1
    const read = vi.fn().mockResolvedValueOnce({ value: encoder.encode(whole.slice(0, split)), done: false })
      .mockResolvedValueOnce({ value: encoder.encode(whole.slice(split)), done: false })
      .mockImplementation(() => new Promise(() => {}))
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { getReader: () => ({ read, cancel: async () => {}, releaseLock: vi.fn() }) } })
    vi.stubGlobal('fetch', fetchMock)
    const { callback } = connect()
    await flushPromises()
    expect(callback.mock.calls).toEqual([[4]])
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/missions/mission%2Fid/workspace/events'), expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('reconnects clean EOF for a fresh watermark and cancels retry when hidden', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200,
      body: { getReader: () => ({ read: async () => ({ done: true }), cancel: async () => {}, releaseLock: vi.fn() }) } })
    vi.stubGlobal('fetch', fetchMock)
    const { client } = connect()
    await vi.advanceTimersByTimeAsync(1001)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    client.disconnect()
    await vi.advanceTimersByTimeAsync(60000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('stops dispatching buffered revisions when the subscription is disconnected', async () => {
    const cancel = vi.fn()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode(frame(1) + frame(2))) }, cancel
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream)))
    const callback = vi.fn(() => client.disconnect())
    const { client } = connect(callback)
    await flushPromises()
    expect(callback.mock.calls).toEqual([[1]])
    expect(cancel).toHaveBeenCalledOnce()
    expect(stream.locked).toBe(false)
  })

  it('ignores a superseded fetch response instead of disconnecting its replacement', async () => {
    let resolveOld!: (response: Response) => void
    let current!: ReadableStreamDefaultController<Uint8Array>
    const stream = new ReadableStream<Uint8Array>({ start(controller) { current = controller } })
    const fetchMock = vi.fn().mockReturnValueOnce(new Promise<Response>(resolve => { resolveOld = resolve }))
      .mockResolvedValueOnce(new Response(stream))
    vi.stubGlobal('fetch', fetchMock)
    const { client, callback } = connect()
    client.connect('mission/id', callback)
    await flushPromises()
    resolveOld(new Response('', { status: 403 }))
    await flushPromises()
    current.enqueue(new TextEncoder().encode(frame(3)))
    await flushPromises()
    expect(callback.mock.calls).toEqual([[3]])
    client.disconnect()
    await flushPromises()
    expect(stream.locked).toBe(false)
  })

  it('keeps the idle watchdog alive on comment heartbeats', async () => {
    vi.useFakeTimers()
    let current!: ReadableStreamDefaultController<Uint8Array>
    const stream = new ReadableStream<Uint8Array>({ start(controller) { current = controller } })
    const fetchMock = vi.fn().mockResolvedValue(new Response(stream))
    vi.stubGlobal('fetch', fetchMock)
    const { client } = connect()
    for (let index = 0; index < 3; index++) {
      await vi.advanceTimersByTimeAsync(30000)
      current.enqueue(new TextEncoder().encode(': heartbeat\r\n\r\n'))
      await vi.advanceTimersByTimeAsync(0)
    }
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false)
    client.disconnect()
    await vi.advanceTimersByTimeAsync(0)
    expect(stream.locked).toBe(false)
  })

  it.each([401, 403, 404])('stops on permanent access errors (%s)', async status => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status })
    vi.stubGlobal('fetch', fetchMock)
    connect()
    await vi.advanceTimersByTimeAsync(60000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
