import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initUiZoomControl, zoomIn } from '@/composables/useUiZoom'
import ZoomIndicator from './ZoomIndicator.vue'

describe('ZoomIndicator', () => {
  let dispose: (() => void) | null = null

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
  })

  afterEach(() => {
    dispose?.()
    dispose = null
    vi.useRealTimers()
  })

  it('未进入缩放交互时不渲染', () => {
    const wrapper = mount(ZoomIndicator)
    expect(wrapper.find('.ui-zoom-osd').exists()).toBe(false)
    wrapper.unmount()
  })

  it('缩放时展示当前百分比，减号与百分比复位可用', async () => {
    dispose = initUiZoomControl({ apply: vi.fn() })
    const wrapper = mount(ZoomIndicator)

    zoomIn()
    await flushPromises()
    expect(wrapper.find('.ui-zoom-osd').exists()).toBe(true)
    expect(wrapper.find('.uzo-value').text()).toBe('120%')

    await wrapper.get('[aria-label="缩小 (Ctrl+-)"]').trigger('click')
    expect(wrapper.find('.uzo-value').text()).toBe('100%')

    zoomIn()
    zoomIn()
    await flushPromises()
    await wrapper.get('.uzo-value').trigger('click')
    expect(wrapper.find('.uzo-value').text()).toBe('100%')

    wrapper.unmount()
  })

  it('空闲后自动隐藏', async () => {
    dispose = initUiZoomControl({ apply: vi.fn() })
    const wrapper = mount(ZoomIndicator)

    zoomIn()
    await flushPromises()
    expect(wrapper.find('.ui-zoom-osd').exists()).toBe(true)

    vi.advanceTimersByTime(1400)
    await flushPromises()
    expect(wrapper.find('.ui-zoom-osd').exists()).toBe(false)
    wrapper.unmount()
  })
})
