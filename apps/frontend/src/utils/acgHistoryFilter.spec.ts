import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ACG_HISTORY_ROLE_CHANGE_EVENT,
  acgHistoryRoleDomain,
  loadAcgHistoryRole,
  saveAcgHistoryRole
} from './acgHistoryFilter'

describe('ACG history role filter', () => {
  beforeEach(() => localStorage.clear())

  it('maps stable roles to backend domains', () => {
    expect(acgHistoryRoleDomain('all')).toBeUndefined()
    expect(acgHistoryRoleDomain('lawyer')).toBe('legal')
    expect(acgHistoryRoleDomain('teacher')).toBe('education')
  })

  it('persists and broadcasts role changes', () => {
    const listener = vi.fn()
    window.addEventListener(ACG_HISTORY_ROLE_CHANGE_EVENT, listener)

    saveAcgHistoryRole('programmer')

    expect(loadAcgHistoryRole()).toBe('programmer')
    expect(listener).toHaveBeenCalledOnce()
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toBe('programmer')
    window.removeEventListener(ACG_HISTORY_ROLE_CHANGE_EVENT, listener)
  })
})
