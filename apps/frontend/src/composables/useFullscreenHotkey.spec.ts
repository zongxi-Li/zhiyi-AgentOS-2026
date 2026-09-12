import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initFullscreenHotkeyControl } from './useFullscreenHotkey'

const fireKeydown = (init: KeyboardEventInit & { key: string }): KeyboardEvent => {
  const event = new KeyboardEvent('keydown', { cancelable: true, bubbles: true, ...init })
  window.dispatchEvent(event)
  return event
}

describe('useFullscreenHotkey', () => {
  let toggle: ReturnType<typeof vi.fn>
  let dispose: (() => void) | null = null

  beforeEach(() => {
    toggle = vi.fn()
  })

  afterEach(() => {
    dispose?.()
    dispose = null
  })

  it('F11 触发全屏切换并阻止默认行为', () => {
    dispose = initFullscreenHotkeyControl({ toggle })

    const event = fireKeydown({ key: 'F11', code: 'F11' })

    expect(toggle).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it('按住 F11 的 auto-repeat 不重复切换', () => {
    dispose = initFullscreenHotkeyControl({ toggle })

    fireKeydown({ key: 'F11', code: 'F11', repeat: true })
    fireKeydown({ key: 'F11', code: 'F11', repeat: true })

    expect(toggle).not.toHaveBeenCalled()
  })

  it('其他按键不触发全屏切换', () => {
    dispose = initFullscreenHotkeyControl({ toggle })

    fireKeydown({ key: 'Escape' })
    fireKeydown({ key: 'f', code: 'KeyF' })
    fireKeydown({ key: 'F12', code: 'F12' })

    expect(toggle).not.toHaveBeenCalled()
  })

  it('dispose 后按键不再生效', () => {
    const disposer = initFullscreenHotkeyControl({ toggle })
    disposer()
    dispose = null

    fireKeydown({ key: 'F11', code: 'F11' })

    expect(toggle).not.toHaveBeenCalled()
  })

  it('dispose 后可重新初始化', () => {
    initFullscreenHotkeyControl({ toggle: vi.fn() })()
    dispose = initFullscreenHotkeyControl({ toggle })

    fireKeydown({ key: 'F11', code: 'F11' })

    expect(toggle).toHaveBeenCalledTimes(1)
  })

  it('幂等：重复初始化返回同一个清理函数', () => {
    dispose = initFullscreenHotkeyControl({ toggle })

    expect(initFullscreenHotkeyControl({ toggle: vi.fn() })).toBe(dispose)
  })
})
