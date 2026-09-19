import { describe, expect, it } from 'vitest'
import { statusSemanticColor, statusSemanticTone, statusToneClass } from './statusSemantic'

describe('statusSemanticTone', () => {
  it('maps terminal success states to the success tone', () => {
    expect(statusSemanticTone('succeeded')).toBe('success')
    expect(statusSemanticTone('COMPLETED')).toBe('success')
    expect(statusSemanticTone('committed')).toBe('success')
  })

  it('maps active states to the running tone', () => {
    expect(statusSemanticTone('running')).toBe('running')
    expect(statusSemanticTone('executed')).toBe('running')
  })

  it('keeps waiting and retry distinct', () => {
    expect(statusSemanticTone('pending')).toBe('waiting')
    expect(statusSemanticTone('waiting_review')).toBe('waiting')
    expect(statusSemanticTone('retrying')).toBe('retry')
    expect(statusSemanticTone('degraded')).toBe('retry')
  })

  it('maps failure family to the failed tone', () => {
    expect(statusSemanticTone('failed')).toBe('failed')
    expect(statusSemanticTone('contract_violation')).toBe('failed')
    expect(statusSemanticTone('cancelled')).toBe('failed')
  })

  it('maps identity and flow vocabulary', () => {
    expect(statusSemanticTone('canonical')).toBe('artifact')
    expect(statusSemanticTone('available')).toBe('success')
    expect(statusSemanticTone('unproven')).toBe('waiting')
  })

  it('falls back to muted for unknown or empty states', () => {
    expect(statusSemanticTone('')).toBe('muted')
    expect(statusSemanticTone(null)).toBe('muted')
    expect(statusSemanticTone('some_future_state')).toBe('muted')
  })
})

describe('status tone helpers', () => {
  it('renders the matching tone class', () => {
    expect(statusToneClass('succeeded')).toBe('tone-success')
    expect(statusToneClass('retrying')).toBe('tone-retry')
    expect(statusToneClass(undefined)).toBe('tone-muted')
  })

  it('resolves colors through semantic CSS variables', () => {
    expect(statusSemanticColor('running')).toBe('var(--sem-running)')
    expect(statusSemanticColor('weird')).toBe('var(--wb-text-muted)')
  })
})
