import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { useWorkbenchLayout } from './useWorkbenchLayout'

const mountLayoutHost = () => {
  let captured: ReturnType<typeof useWorkbenchLayout> | null = null
  const Host = defineComponent({
    setup() {
      captured = useWorkbenchLayout()
      return () => h('div', { ref: captured.containerRef })
    }
  })
  const wrapper = mount(Host)
  return { layout: captured!, wrapper }
}

describe('useWorkbenchLayout restoreLeftPane', () => {
  it('restores a left pane that was auto-hidden by dragging to its minimum width', () => {
    const { layout, wrapper } = mountLayoutHost()

    layout.leftPaneWidth.value = 240
    layout.syncAutoHidden()
    expect(layout.leftAutoHidden.value).toBe(true)

    layout.restoreLeftPane()

    expect(layout.leftPaneWidth.value).toBe(320)
    expect(layout.leftAutoHidden.value).toBe(false)
    expect(layout.rightCollapsedByUser.value).toBe(false)
    wrapper.unmount()
  })

  it('yields the right pane when the window cannot fit left plus right plus main', () => {
    const { layout, wrapper } = mountLayoutHost()
    const container = wrapper.get('div').element as HTMLElement
    // 850px：右侧先被自动隐藏（<1296），左侧也放不下（<896）——两侧都藏的最窄区间。
    Object.defineProperty(container, 'clientWidth', { value: 850, configurable: true })
    layout.containerRef.value = container
    layout.syncAutoHidden()
    expect(layout.leftAutoHidden.value).toBe(true)
    expect(layout.rightCollapsedByUser.value).toBe(false)

    layout.restoreLeftPane()

    expect(layout.rightCollapsedByUser.value).toBe(true)
    expect(layout.leftPaneWidth.value).toBeGreaterThanOrEqual(240)
    expect(layout.leftPaneWidth.value).toBeLessThanOrEqual(320)
    expect(layout.leftAutoHidden.value).toBe(false)
    wrapper.unmount()
  })
})
