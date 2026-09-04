import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const windowMocks = vi.hoisted(() => ({
  getCurrentWindow: vi.fn(),
  isMaximized: vi.fn(),
  onResized: vi.fn(),
  minimize: vi.fn(),
  toggleMaximize: vi.fn(),
  close: vi.fn()
}))

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: windowMocks.getCurrentWindow
}))

import DesktopWindowControls from './DesktopWindowControls.vue'

type ResizeListener = (payload: unknown) => void

const mountControls = async (initialMaximized = false) => {
  windowMocks.getCurrentWindow.mockReturnValue(windowMocks)
  windowMocks.isMaximized.mockResolvedValue(initialMaximized)
  let resizeListener: ResizeListener | null = null
  windowMocks.onResized.mockImplementation((listener: ResizeListener) => {
    resizeListener = listener
    return Promise.resolve(() => {
      resizeListener = null
    })
  })

  const wrapper = mount(DesktopWindowControls)
  await flushPromises()
  return {
    wrapper,
    emitResize: async () => {
      resizeListener?.({})
      await flushPromises()
    }
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DesktopWindowControls', () => {
  it('does not break the page when the Tauri bridge is unavailable', async () => {
    windowMocks.getCurrentWindow.mockImplementationOnce(() => {
      throw new Error('Tauri bridge unavailable')
    })

    const wrapper = mount(DesktopWindowControls)
    await flushPromises()

    expect(wrapper.find('.desktop-window-controls').exists()).toBe(false)
    expect(windowMocks.onResized).not.toHaveBeenCalled()
  })

  it('renders the three window buttons with neutral icons', () => {
    return mountControls().then(({ wrapper }) => {
      expect(wrapper.findAll('.dwc-button')).toHaveLength(3)
      expect(wrapper.get('[aria-label="最小化"]').exists()).toBe(true)
      expect(wrapper.get('[aria-label="最大化"]').exists()).toBe(true)
      expect(wrapper.get('[aria-label="关闭"]').exists()).toBe(true)
    })
  })

  it('invokes the native window APIs on click', async () => {
    const { wrapper } = await mountControls()

    await wrapper.get('[aria-label="最小化"]').trigger('click')
    await wrapper.get('[aria-label="最大化"]').trigger('click')
    await wrapper.get('[aria-label="关闭"]').trigger('click')

    expect(windowMocks.minimize).toHaveBeenCalledTimes(1)
    expect(windowMocks.toggleMaximize).toHaveBeenCalledTimes(1)
    expect(windowMocks.close).toHaveBeenCalledTimes(1)
  })

  it('syncs the restore icon with the real window state on resize', async () => {
    const { wrapper, emitResize } = await mountControls(false)
    expect(wrapper.find('[aria-label="向下还原"]').exists()).toBe(false)

    windowMocks.isMaximized.mockResolvedValue(true)
    await emitResize()

    expect(wrapper.find('[aria-label="最大化"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="向下还原"]').exists()).toBe(true)

    windowMocks.isMaximized.mockResolvedValue(false)
    await emitResize()
    expect(wrapper.get('[aria-label="最大化"]').exists()).toBe(true)
  })

  it('reads the initial maximized state on mount', async () => {
    const { wrapper } = await mountControls(true)

    expect(windowMocks.isMaximized).toHaveBeenCalled()
    expect(wrapper.get('[aria-label="向下还原"]').exists()).toBe(true)
  })

  it('stops listening to window resizes on unmount', async () => {
    windowMocks.isMaximized.mockResolvedValue(false)
    const unlisten = vi.fn()
    windowMocks.onResized.mockResolvedValue(unlisten)

    const wrapper = mount(DesktopWindowControls)
    await flushPromises()
    wrapper.unmount()
    await flushPromises()

    expect(unlisten).toHaveBeenCalledTimes(1)
  })
})
