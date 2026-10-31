import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useChatStore } from './chat'
import { chatApi } from '@/services/api/chat'
import { conversationApi } from '@/services/api/conversation'

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}
const stream = (contextId = 'new-context') => {
  let writer!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start(controller) { writer = controller } })
  return {
    response: new Response(body, { headers: { 'X-Chat-Context-Id': contextId } }),
    frame: (event: string, data: object, requestId?: string) => writer.enqueue(new TextEncoder().encode(
      `event:${event}\ndata:${JSON.stringify({ event, data, requestId })}\n\n`)),
    close: () => writer.close()
  }
}

describe('Message request ownership (PR-UI-02A-R2)', () => {
  beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()) })
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('ignores an old file response and its finally while a new request owns the composer', async () => {
    const old = deferred<any>(); const next = deferred<any>()
    vi.spyOn(chatApi, 'sendMessage').mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise)
    const store = useChatStore()
    const first = store.sendMessage('old', '/old-file')
    store.clearMessages()
    const second = store.sendMessage('new', '/new-file')
    old.resolve({ contextId: 'old-context', text: 'obsolete' }); await first
    expect(store.contextId).toBeNull()
    expect(store.messages.map(item => item.content)).toEqual(['new'])
    expect(store.loading).toBe(true)
    next.resolve({ contextId: 'new-context', text: 'owned' }); await second
    expect(store.contextId).toBe('new-context')
    expect(store.messages.map(item => item.content)).toEqual(['new', 'owned'])
    expect(store.loading).toBe(false)
  })

  it('discards an obsolete file failure without rejecting into the new composer', async () => {
    const old = deferred<any>()
    vi.spyOn(chatApi, 'sendMessage').mockReturnValue(old.promise)
    const store = useChatStore(); const first = store.sendMessage('old', '/file')
    store.clearMessages(); store.addMessage({ id: 'new', role: 'user', content: 'new' })
    old.reject(new Error('late failure'))
    await expect(first).resolves.toBeUndefined()
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe('new')
  })
  it('does not let an older history deletion clear a newer message request', async () => {
    const deletion = deferred<any>(), reply = deferred<any>()
    vi.spyOn(chatApi, 'clearHistory').mockReturnValue(deletion.promise)
    vi.spyOn(chatApi, 'sendMessage').mockReturnValue(reply.promise)
    const store = useChatStore(); store.contextId = 'same-context'
    const clearing = store.clearHistory()
    const sending = store.sendMessage('new request', '/file')
    deletion.resolve({}); await clearing
    expect(store.messages[0].content).toBe('new request'); expect(store.loading).toBe(true)
    reply.resolve({ contextId: 'same-context', text: 'new response' }); await sending
    expect(store.messages.at(-1)?.content).toBe('new response')
  })

  it('ignores late SSE frames at the same message index and preserves the new stream state', async () => {
    const old = stream('old-context'); const next = stream()
    const fetchMock = vi.fn().mockResolvedValueOnce(old.response).mockResolvedValueOnce(next.response)
    vi.stubGlobal('fetch', fetchMock)
    const store = useChatStore(); const first = store.sendMessageStream('old')
    old.frame('content_delta', { delta: 'partial old' }); await flushPromises()
    store.clearMessages()
    const second = store.sendMessageStream('new'); await flushPromises()
    // Deliberately non-cooperative transport: abort does not prevent another frame.
    old.frame('done', { status: 'completed', contextId: 'wrong-context' }); await first
    expect(store.contextId).toBe('new-context')
    expect(store.messages.at(-1)?.content).toBe('')
    expect(store.isStreaming).toBe(true); expect(store.loading).toBe(true)
    next.frame('content_delta', { delta: 'complete new' })
    next.frame('done', { status: 'completed', contextId: 'new-context' }); next.close(); await second
    expect(store.messages.at(-1)?.content).toBe('complete new')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(store.isStreaming).toBe(false)
  })

  it('discards late SSE headers after a new Conversation starts', async () => {
    const header = deferred<Response>(); const old = stream('wrong-context')
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(header.promise))
    const store = useChatStore(); const first = store.sendMessageStream('old')
    store.clearMessages(); store.contextId = 'new-context'
    header.resolve(old.response); await first
    expect(store.contextId).toBe('new-context'); expect(store.messages).toEqual([])
  })

  it('invalidates message writes when loading a different history', async () => {
    const old = deferred<any>()
    vi.spyOn(chatApi, 'sendMessage').mockReturnValue(old.promise)
    vi.spyOn(chatApi, 'getHistory').mockResolvedValue([{ role: 'assistant', content: 'history' }])
    vi.spyOn(conversationApi, 'getConversation').mockResolvedValue({ contextId: 'history', roleId: 'role' } as any)
    const store = useChatStore(); const first = store.sendMessage('old', '/file')
    await store.loadHistory('history')
    old.resolve({ contextId: 'wrong', text: 'obsolete' }); await first
    expect(store.contextId).toBe('history'); expect(store.currentRoleId).toBe('role')
    expect(store.messages.map(item => item.content)).toEqual(['history'])
  })

  it('a delayed cancel action aborts only the stream it originally targeted', async () => {
    const old = stream('old-context'); const next = stream()
    const cancel = deferred<any>()
    vi.spyOn(chatApi, 'cancelExecution').mockReturnValue(cancel.promise)
    const fetchMock = vi.fn().mockResolvedValueOnce(old.response).mockResolvedValueOnce(next.response)
    vi.stubGlobal('fetch', fetchMock)
    const store = useChatStore(); const first = store.sendMessageStream('old')
    old.frame('content_delta', { delta: 'old' }); await flushPromises()
    // Legacy streams without request IDs abort synchronously, so supply a real ID.
    old.frame('content_delta', { delta: '' }, 'old-request'); await flushPromises()
    const stopping = store.cancelMessageStream()
    expect(chatApi.cancelExecution).toHaveBeenCalledWith('old-request')
    store.clearMessages(); const second = store.sendMessageStream('new'); await flushPromises()
    cancel.resolve({}); await stopping
    expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(false)
    old.frame('done', { status: 'completed' }); await first
    next.frame('content_delta', { delta: 'new' }); next.frame('done', { status: 'completed' }); next.close()
    await second
  })
})
