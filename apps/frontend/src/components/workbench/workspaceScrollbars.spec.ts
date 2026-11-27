import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createWorkspaceScrollbars } from './workspaceScrollbars'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())
const surface = () => {
  const scrollbars = createWorkspaceScrollbars()
  const root = document.createElement('section')
  const first = root.appendChild(document.createElement('div'))
  const second = root.appendChild(document.createElement('div'))
  root.addEventListener('scroll', scrollbars.onScroll, true)
  return { ...scrollbars, first, second }
}
it('reveals the actual nested scroller and fades after scrolling stops', () => {
  const state = surface()
  expect(state.first.classList.contains('workspace-scroll-active')).toBe(false)
  state.first.dispatchEvent(new Event('scroll'))
  expect(state.first.classList.contains('workspace-scroll-active')).toBe(true)
  vi.advanceTimersByTime(800)
  state.first.dispatchEvent(new Event('scroll'))
  vi.advanceTimersByTime(800)
  expect(state.first.classList.contains('workspace-scroll-active')).toBe(true)
  vi.advanceTimersByTime(100)
  expect(state.first.classList.contains('workspace-scroll-active')).toBe(false)
})
it('keeps independent visibility timers for separate scrolling areas', () => {
  const state = surface()
  state.first.dispatchEvent(new Event('scroll'))
  vi.advanceTimersByTime(500)
  state.second.dispatchEvent(new Event('scroll'))
  vi.advanceTimersByTime(400)
  expect(state.first.classList.contains('workspace-scroll-active')).toBe(false)
  expect(state.second.classList.contains('workspace-scroll-active')).toBe(true)
  state.clear()
})
it('clears timers and visible state on workspace deactivation or disposal', () => {
  const state = surface()
  state.first.dispatchEvent(new Event('scroll'))
  state.second.dispatchEvent(new Event('scroll'))
  state.clear()
  expect(vi.getTimerCount()).toBe(0)
  expect(state.first.className).toBe('')
  expect(state.second.className).toBe('')
})
