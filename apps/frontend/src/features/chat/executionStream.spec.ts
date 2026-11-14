import { afterEach, describe, expect, it, vi } from 'vitest'
import { followChatExecution, startChatExecution } from './executionStream'

const response = (events: any[]) => new Response(events.map(event => `data:${JSON.stringify(event)}\n\n`).join(''))
afterEach(() => {vi.unstubAllGlobals(); vi.restoreAllMocks()})

describe('chat execution subscription recovery', () => {
  it('reuses the command ID and body after an acknowledgement is lost', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('network lost'))
      .mockResolvedValueOnce(Response.json({chatExecutionId: 'execution', contextId: 'context'}))
    vi.stubGlobal('fetch', fetch)
    const result = await startChatExecution({clientRequestId: 'same-command', text: 'once'}, new AbortController().signal)
    expect(result.chatExecutionId).toBe('execution')
    expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('replaces a stale projection on reconnect and deduplicates already seen deltas', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response([
      {event: 'snapshot', sequence: 1, data: {message: {content: 'A'}}},
      {event: 'content_delta', sequence: 2, data: {delta: 'B'}},
    ])).mockResolvedValueOnce(response([
      {event: 'snapshot', sequence: 3, data: {message: {content: 'ABC'}}},
      {event: 'content_delta', sequence: 3, data: {delta: 'C'}},
      {event: 'content_delta', sequence: 4, data: {delta: 'D'}},
      {event: 'done', sequence: 5, data: {status: 'completed'}},
    ]))
    vi.stubGlobal('fetch', fetch)
    let content = ''
    const reconnect = vi.fn()
    for await (const event of followChatExecution('execution', new AbortController().signal, reconnect)) {
      if (event.event === 'snapshot') content = event.data.message.content
      if (event.event === 'content_delta') content += event.data.delta
    }
    expect(content).toBe('ABCD')
    expect(reconnect).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[1][0]).toContain('/execution/events?after=2')
    expect(fetch.mock.calls.every(call => !call[1].method)).toBe(true)
  })

  it('does not reconnect after an ownership rejection or a terminal error', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('', {status: 403}))
    vi.stubGlobal('fetch', fetch)
    await expect((async () => {for await (const _ of followChatExecution('execution', new AbortController().signal, vi.fn())) {}})()).rejects.toThrow('403')
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
