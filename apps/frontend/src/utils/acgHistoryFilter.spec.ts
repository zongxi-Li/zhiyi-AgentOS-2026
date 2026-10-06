import { describe, expect, it, vi } from 'vitest'
import { ACG_HISTORY_SOURCES, ACG_RUN_INVALIDATED_EVENT, notifyAcgRunInvalidated } from './acgHistoryFilter'

describe('acg history filter helpers', () => {
  it('exposes the combined run sources constant', () => {
    expect(ACG_HISTORY_SOURCES).toBe('acg,agent,chat,legacy_agent_chat')
  })

  it('broadcasts run invalidation for non-empty run ids only', () => {
    const listener = vi.fn()
    window.addEventListener(ACG_RUN_INVALIDATED_EVENT, listener)

    notifyAcgRunInvalidated('  run_123  ')
    notifyAcgRunInvalidated('   ')

    expect(listener).toHaveBeenCalledOnce()
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ runId: 'run_123' })
    window.removeEventListener(ACG_RUN_INVALIDATED_EVENT, listener)
  })
})
