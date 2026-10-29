import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initUiZoom } from './uiZoom'
import type { KinlinDesktopBridge } from './bridge'
import { uiZoomState } from '@/composables/useUiZoom'

// 完整桥 mock：缩放只消费 zoom.setZoomFactor，其余面照 bridge 合同占位。
const createBridge = () =>
  ({
    window: {
      minimize: vi.fn(),
      toggleMaximize: vi.fn(),
      close: vi.fn(),
      isMaximized: vi.fn(async () => false),
      isFullscreen: vi.fn(async () => false),
      setFullscreen: vi.fn(async () => {}),
      onMaximizeChanged: vi.fn(() => () => {})
    },
    zoom: {
      setZoomFactor: vi.fn()
    },
    dialog: {
      openFile: vi.fn(async () => null),
      openDirectory: vi.fn(async () => null)
    },
    notify: vi.fn(),
    openExternal: vi.fn(async () => {}),
    appInfo: vi.fn(async () => ({ version: '0.0.0-test', platform: 'win32', packaged: false }))
  }) as unknown as KinlinDesktopBridge

describe('electron uiZoom', () => {
  let dispose: (() => void) | null = null

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.removeItem('layout.ui_zoom_level')
  })

  afterEach(() => {
    // initUiZoomControl 幂等返回同一清理函数：这里兜底清理，防止上一用例短路遗留监听。
    dispose?.()
    dispose = null
    vi.useRealTimers()
    delete (window as any).kinlinDesktop
    localStorage.removeItem('layout.ui_zoom_level')
  })

  it('restores the stored zoom level on initialization', () => {
    window.kinlinDesktop = createBridge()
    localStorage.setItem('layout.ui_zoom_level', '1')

    dispose = initUiZoom()

    expect(uiZoomState.level).toBe(1)
  })

  it('applies the zoom factor through the bridge after the Ctrl+wheel debounce', () => {
    const bridge = createBridge()
    window.kinlinDesktop = bridge

    dispose = initUiZoom()

    // composable 在 capture 阶段监听 window；deltaY 为正对应放大一档（level 0→1）。
    window.dispatchEvent(new WheelEvent('wheel', { ctrlKey: true, deltaY: 120, cancelable: true }))
    expect(uiZoomState.level).toBe(1)

    vi.advanceTimersByTime(60)
    expect(bridge.zoom.setZoomFactor).toHaveBeenCalledTimes(1)
    expect(bridge.zoom.setZoomFactor).toHaveBeenCalledWith(1.2)
  })

  it('does not throw on Ctrl+wheel when the bridge is missing', () => {
    dispose = initUiZoom()

    expect(() => {
      window.dispatchEvent(new WheelEvent('wheel', { ctrlKey: true, deltaY: 120, cancelable: true }))
      vi.advanceTimersByTime(60)
    }).not.toThrow()
  })
})
