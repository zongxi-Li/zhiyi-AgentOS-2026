import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { KinlinDesktopBridge } from '@/platform/electron/bridge'

import ElectronWindowControls from './ElectronWindowControls.vue'

// 不依赖平台桥实现，直接在 window.kinlinDesktop 上注入完整的 Electron 桥 mock。
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

const installBridge = (): KinlinDesktopBridge => {
  const bridge = createBridge()
  window.kinlinDesktop = bridge
  return bridge
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  delete (window as any).kinlinDesktop
})

describe('ElectronWindowControls', () => {
  it('does not break the page when the Electron bridge is unavailable', async () => {
    const wrapper = mount(ElectronWindowControls)
    await flushPromises()

    expect(wrapper.find('.desktop-window-controls').exists()).toBe(false)
    expect(wrapper.find('.dwc-button').exists()).toBe(false)
  })

  it('renders the three window buttons and invokes the bridge APIs on click', async () => {
    const bridge = installBridge()
    const wrapper = mount(ElectronWindowControls)
    await flushPromises()

    expect(wrapper.findAll('.dwc-button')).toHaveLength(3)

    await wrapper.get('[aria-label="最小化"]').trigger('click')
    await wrapper.get('[aria-label="最大化"]').trigger('click')
    await wrapper.get('[aria-label="关闭"]').trigger('click')

    expect(bridge.window.minimize).toHaveBeenCalledTimes(1)
    expect(bridge.window.toggleMaximize).toHaveBeenCalledTimes(1)
    expect(bridge.window.close).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('marks the window as maximized once isMaximized resolves', async () => {
    const bridge = installBridge()
    vi.mocked(bridge.window.isMaximized).mockResolvedValue(true)

    const wrapper = mount(ElectronWindowControls)
    await flushPromises()

    expect(wrapper.find('[aria-label="最大化"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="向下还原"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('updates the restore icon when onMaximizeChanged fires', async () => {
    const bridge = installBridge()
    vi.mocked(bridge.window.isMaximized).mockResolvedValue(true)

    const wrapper = mount(ElectronWindowControls)
    await flushPromises()

    expect(wrapper.get('[aria-label="向下还原"]').exists()).toBe(true)

    const [listener] = vi.mocked(bridge.window.onMaximizeChanged).mock.calls[0]
    listener(false)
    await nextTick()

    expect(wrapper.get('[aria-label="最大化"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('stops listening to maximize changes on unmount', async () => {
    const unlisten = vi.fn()
    const bridge = createBridge()
    vi.mocked(bridge.window.onMaximizeChanged).mockReturnValue(unlisten)
    window.kinlinDesktop = bridge

    const wrapper = mount(ElectronWindowControls)
    await flushPromises()
    wrapper.unmount()
    await flushPromises()

    expect(unlisten).toHaveBeenCalledTimes(1)
  })

  it('no longer reacts to F11 (fullscreen moved to Main before-input-event)', async () => {
    const bridge = installBridge()
    const wrapper = mount(ElectronWindowControls)
    await flushPromises()

    const event = new KeyboardEvent('keydown', { key: 'F11', cancelable: true })
    window.dispatchEvent(event)
    await flushPromises()

    // Main 进程接管 F11 后，渲染层若再响应会双 toggle（等于没切），这里钉死不再监听。
    expect(event.defaultPrevented).toBe(false)
    expect(bridge.window.setFullscreen).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
