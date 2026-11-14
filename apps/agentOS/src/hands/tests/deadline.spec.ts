import { afterEach, expect, it, vi } from 'vitest'
import { armDeadline } from '../hands/deadline.ts'

afterEach(() => vi.useRealTimers())

it('arms no implicit deadline', () => {
  vi.useFakeTimers()
  const expire = vi.fn()
  const cancel = armDeadline(undefined, expire)
  expect(vi.getTimerCount()).toBe(0)
  vi.advanceTimersByTime(900000)
  expect(expire).not.toHaveBeenCalled()
  cancel()
})

it('does not overflow the Node timer range and can cancel a long requested deadline', () => {
  vi.useFakeTimers()
  const expire = vi.fn()
  const cancel = armDeadline(2147483647 + 10000, expire)
  vi.advanceTimersByTime(2147483647)
  expect(expire).not.toHaveBeenCalled()
  cancel()
  vi.advanceTimersByTime(10000)
  expect(expire).not.toHaveBeenCalled()
})
