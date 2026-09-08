import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  UI_ZOOM_MAX_LEVEL,
  UI_ZOOM_MIN_LEVEL,
  UI_ZOOM_STORAGE_KEY,
  initUiZoomControl,
  resetZoom,
  uiZoomFactor,
  uiZoomState,
  zoomIn,
  zoomOut
} from './useUiZoom'

// jsdom 的 Event 实例可按需补齐 wheel 专属字段，避免依赖 WheelEvent 构造器的完整性。
const createWheelEvent = (init: { deltaY: number; ctrlKey?: boolean; deltaMode?: number }) => {
  const event = new Event('wheel', { cancelable: true, bubbles: true })
  Object.defineProperty(event, 'ctrlKey', { value: init.ctrlKey ?? false })
  Object.defineProperty(event, 'deltaY', { value: init.deltaY })
  Object.defineProperty(event, 'deltaMode', { value: init.deltaMode ?? 0 })
  return event
}

const fireKeydown = (init: KeyboardEventInit & { key: string }): Event => {
  const event = new KeyboardEvent('keydown', { cancelable: true, bubbles: true, ...init })
  window.dispatchEvent(event)
  return event
}

describe('useUiZoom', () => {
  let apply: ReturnType<typeof vi.fn>
  let dispose: (() => void) | null = null

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    apply = vi.fn()
  })

  afterEach(() => {
    dispose?.()
    dispose = null
    vi.useRealTimers()
  })

  it('未初始化（Web 构建）时所有缩放入口都不生效', () => {
    zoomIn()
    resetZoom()
    window.dispatchEvent(createWheelEvent({ deltaY: 100, ctrlKey: true }))

    expect(apply).not.toHaveBeenCalled()
    expect(uiZoomState.level).toBe(0)
    expect(uiZoomState.visible).toBe(false)
  })

  it('Ctrl+滚轮按档位缩放并阻止默认行为与画布冒泡', () => {
    dispose = initUiZoomControl({ apply })

    const event = createWheelEvent({ deltaY: 100, ctrlKey: true })
    window.dispatchEvent(event)

    expect(uiZoomState.level).toBe(1)
    expect(event.defaultPrevented).toBe(true)
    expect(uiZoomState.visible).toBe(true)

    vi.advanceTimersByTime(50)
    expect(apply).toHaveBeenLastCalledWith(uiZoomFactor(1))
    expect(localStorage.getItem(UI_ZOOM_STORAGE_KEY)).toBe('1')
  })

  it('普通滚轮不触发界面缩放', () => {
    dispose = initUiZoomControl({ apply })

    window.dispatchEvent(createWheelEvent({ deltaY: 100 }))
    window.dispatchEvent(createWheelEvent({ deltaY: -100 }))

    expect(uiZoomState.level).toBe(0)
    vi.advanceTimersByTime(50)
    expect(apply).not.toHaveBeenCalled()
  })

  it('Ctrl+滚轮在子元素上也会被窗口层拦截，不再传给组件处理器', () => {
    dispose = initUiZoomControl({ apply })

    const childHandler = vi.fn()
    const child = document.createElement('div')
    child.addEventListener('wheel', childHandler)
    document.body.appendChild(child)

    child.dispatchEvent(createWheelEvent({ deltaY: 100, ctrlKey: true }))

    expect(childHandler).not.toHaveBeenCalled()
    expect(uiZoomState.level).toBe(1)
    child.remove()
  })

  it('Ctrl+= 放大、Ctrl+- 缩小、Ctrl+0 复位', () => {
    dispose = initUiZoomControl({ apply })

    const zoomInEvent = fireKeydown({ key: '=', code: 'Equal', ctrlKey: true })
    expect(uiZoomState.level).toBe(1)
    expect(zoomInEvent.defaultPrevented).toBe(true)

    const zoomOutEvent = fireKeydown({ key: '-', code: 'Minus', ctrlKey: true })
    expect(uiZoomState.level).toBe(0)
    expect(zoomOutEvent.defaultPrevented).toBe(true)

    zoomIn()
    zoomIn()
    const resetEvent = fireKeydown({ key: '0', code: 'Digit0', ctrlKey: true })
    expect(uiZoomState.level).toBe(0)
    expect(resetEvent.defaultPrevented).toBe(true)

    vi.advanceTimersByTime(50)
    expect(apply).toHaveBeenLastCalledWith(uiZoomFactor(0))
    expect(localStorage.getItem(UI_ZOOM_STORAGE_KEY)).toBe('0')
  })

  it('档位钳制在 [-4, 5] 区间', () => {
    dispose = initUiZoomControl({ apply })

    for (let i = 0; i < 20; i += 1) zoomIn()
    expect(uiZoomState.level).toBe(UI_ZOOM_MAX_LEVEL)

    for (let i = 0; i < 30; i += 1) zoomOut()
    expect(uiZoomState.level).toBe(UI_ZOOM_MIN_LEVEL)

    vi.advanceTimersByTime(50)
    expect(apply).toHaveBeenLastCalledWith(uiZoomFactor(UI_ZOOM_MIN_LEVEL))
  })

  it('初始化时恢复上次档位并短暂提示', () => {
    localStorage.setItem(UI_ZOOM_STORAGE_KEY, '2')
    dispose = initUiZoomControl({ apply })

    expect(uiZoomState.level).toBe(2)
    expect(uiZoomState.visible).toBe(true)

    vi.advanceTimersByTime(50)
    expect(apply).toHaveBeenCalledWith(uiZoomFactor(2))

    vi.advanceTimersByTime(1400)
    expect(uiZoomState.visible).toBe(false)
  })

  it('越界或非法的存量档位会被钳制或忽略', () => {
    localStorage.setItem(UI_ZOOM_STORAGE_KEY, '99')
    dispose = initUiZoomControl({ apply })
    expect(uiZoomState.level).toBe(UI_ZOOM_MAX_LEVEL)
    dispose?.()
    dispose = null

    localStorage.setItem(UI_ZOOM_STORAGE_KEY, 'abc')
    dispose = initUiZoomControl({ apply })
    expect(uiZoomState.level).toBe(0)
  })

  it('重复初始化是幂等的，不会叠加监听', () => {
    const first = initUiZoomControl({ apply })
    const second = initUiZoomControl({ apply: vi.fn() })
    expect(second).toBe(first)

    window.dispatchEvent(createWheelEvent({ deltaY: 100, ctrlKey: true }))
    expect(uiZoomState.level).toBe(1)
    dispose = second
  })

  it('清理后监听全部移除，状态复位', () => {
    dispose = initUiZoomControl({ apply })
    dispose()
    dispose = null

    window.dispatchEvent(createWheelEvent({ deltaY: 100, ctrlKey: true }))
    fireKeydown({ key: '=', code: 'Equal', ctrlKey: true })

    expect(uiZoomState.level).toBe(0)
    expect(apply).not.toHaveBeenCalled()
    expect(uiZoomState.visible).toBe(false)
  })

  it('line 模式的滚轮 delta 按 16px 折算', () => {
    dispose = initUiZoomControl({ apply })

    window.dispatchEvent(createWheelEvent({ deltaY: 4, ctrlKey: true, deltaMode: 1 }))
    expect(uiZoomState.level).toBe(1)
  })
})
