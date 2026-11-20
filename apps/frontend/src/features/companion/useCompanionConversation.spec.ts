import { describe, expect, it, vi } from 'vitest'
import { useCompanionConversation } from './useCompanionConversation'
import { EMPTY_PROGRESS, type ChatPort } from './types'

const build = (chat: ChatPort) => {
  const onReply = vi.fn()
  const onState = vi.fn()
  const onTurn = vi.fn()
  const conversation = useCompanionConversation({
    persona: () => ({ name: '团子', lines: ['我是你的伙伴'] }),
    createPorts: () => ({ chat, progress: { resolveRunId: () => null, read: async () => EMPTY_PROGRESS } }),
    onReply, onState, onTurn
  })
  return { ...conversation, onReply, onState, onTurn }
}

describe('Companion conversation ownership', () => {
  it('falls back on model failure, retaining visible context and current persona', async () => {
    const reply = vi.fn().mockRejectedValue(new Error('offline'))
    const c = build({ reply })
    await c.send('你好')
    expect(c.messages.value.map(m => m.role)).toEqual(['user', 'companion'])
    expect(c.messages.value[1].content).toBe('我是你的伙伴')
    expect(reply.mock.calls[0][1].personaName).toBe('团子')
    expect(c.pending.value).toBe(false)
  })

  it('ignores a second pending turn and does not publish after disposal', async () => {
    let resolve!: (value: string) => void
    const c = build({ reply: () => new Promise(r => { resolve = r }) })
    const first = c.send('你好')
    await c.send('第二次')
    expect(c.messages.value).toHaveLength(1)
    c.dispose()
    resolve('迟到的回复')
    await first
    expect(c.messages.value).toHaveLength(1)
    expect(c.onReply).not.toHaveBeenCalled()
  })

  it('does not turn cancellation into local fallback or an error reply', async () => {
    const c = build({ reply: async () => { throw new DOMException('cancelled', 'AbortError') } })
    await c.send('你好')
    expect(c.messages.value).toHaveLength(1)
    expect(c.onReply).not.toHaveBeenCalled()
    expect(c.pending.value).toBe(false)
  })
})
