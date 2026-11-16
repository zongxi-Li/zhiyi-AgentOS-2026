import { afterEach, expect, it, vi } from 'vitest'
import { armDeadline } from '../hands/deadline.ts'

afterEach(() => vi.useRealTimers())

it('honors a 1800 second deadline without firing at the former 600 second cap', () => {
  vi.useFakeTimers()
  const expire = vi.fn()
  const cancel = armDeadline(1800000, expire)
  vi.advanceTimersByTime(600000)
  expect(expire).not.toHaveBeenCalled()
  vi.advanceTimersByTime(1199999)
  expect(expire).not.toHaveBeenCalled()
  vi.advanceTimersByTime(1)
  expect(expire).toHaveBeenCalledTimes(1)
  cancel()
})

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
