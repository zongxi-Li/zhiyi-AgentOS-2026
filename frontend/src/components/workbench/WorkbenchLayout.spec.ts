import { h, nextTick } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import WorkbenchLayout from './WorkbenchLayout.vue'

const STORAGE_KEY = 'test.workbench.layout'

class TestResizeObserver {
  static instances: TestResizeObserver[] = []
  private readonly callback: ResizeObserverCallback

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    TestResizeObserver.instances.push(this)
  }

  observe() {}
  disconnect() {}
  unobserve() {}

  trigger() {
    this.callback([], this as unknown as ResizeObserver)
  }
}

const mountLayout = () => mount(WorkbenchLayout, {
  props: { storageKey: STORAGE_KEY },
  slots: {
    left: () => h('div', { class: 'slot-left' }, 'left'),
    right: () => h('div', { class: 'slot-right' }, 'right'),
    main: (state: Record<string, unknown>) => h('div', { class: 'slot-main' }, [
      h('span', { class: 'layout-state' }, JSON.stringify({
        leftAutoHidden: state.leftAutoHidden,
        rightAutoHidden: state.rightAutoHidden
      }))
    ])
  }
})

const setContainerWidth = async (wrapper: VueWrapper, width: number) => {
  const root = wrapper.find('.workbench-layout').element
  Object.defineProperty(root, 'clientWidth', { configurable: true, value: width })
  TestResizeObserver.instances[0]?.trigger()
  await nextTick()
}

const layoutState = (wrapper: VueWrapper) => JSON.parse(wrapper.find('.layout-state').text()) as {
  leftAutoHidden: boolean
  rightAutoHidden: boolean
}

describe('WorkbenchLayout', () => {
  const originalResizeObserver = (globalThis as typeof globalThis & { ResizeObserver?: typeof ResizeObserver }).ResizeObserver

  beforeEach(() => {
    localStorage.clear()
    TestResizeObserver.instances = []
    ;(globalThis as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver
  })

  afterEach(() => {
    if (originalResizeObserver) {
      ;(globalThis as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver = originalResizeObserver
    } else {
      delete (globalThis as typeof globalThis & { ResizeObserver?: typeof ResizeObserver }).ResizeObserver
    }
  })

  it('clamps persisted pane widths and keeps only layout state', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      leftPaneWidth: 99999,
      rightPaneWidth: -10,
      leftCollapsedByUser: false,
      rightCollapsedByUser: false,
      runId: 'must-not-be-persisted'
    }))

    const wrapper = mountLayout()

    expect(wrapper.find('.workbench-resize-handle--left').attributes('aria-valuenow')).toBe('520')
    expect(wrapper.find('.workbench-resize-handle--right').attributes('aria-valuenow')).toBe('300')
    await wrapper.find('.workbench-resize-handle--left').trigger('keydown', { key: 'ArrowRight' })
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>
    expect(persisted).toEqual({
      leftPaneWidth: 520,
      rightPaneWidth: 300
    })
    expect(persisted).not.toHaveProperty('runId')
    wrapper.unmount()
  })

  it('auto-hides a pane at its minimum width and restores it by dragging its edge', async () => {
    const wrapper = mountLayout()
    const leftHandle = wrapper.find('.workbench-resize-handle--left')

    await leftHandle.trigger('keydown', { key: 'Home' })
    await nextTick()

    expect(wrapper.find('.workbench-pane--left').exists()).toBe(false)
    expect(layoutState(wrapper).leftAutoHidden).toBe(true)
    expect(wrapper.find('.workbench-resize-handle--left').attributes('aria-valuenow')).toBe('240')
    expect(wrapper.find('.workbench-resize-handle--left').exists()).toBe(true)

    await wrapper.find('.workbench-resize-handle--left').trigger('keydown', { key: 'ArrowRight' })
    await nextTick()

    expect(wrapper.find('.workbench-pane--left').exists()).toBe(true)
    expect(layoutState(wrapper).leftAutoHidden).toBe(false)
    expect(wrapper.find('.workbench-resize-handle--left').attributes('aria-valuenow')).toBe('248')
    wrapper.unmount()
  })

  it('auto-hides the right pane first, restores it on widen, and never persists auto-hidden state', async () => {
    const wrapper = mountLayout()

    await setContainerWidth(wrapper, 1000)
    expect(wrapper.find('.workbench-pane--right').exists()).toBe(false)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: true,
      leftAutoHidden: false
    })
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>
    expect(persisted).not.toHaveProperty('rightAutoHidden')
    expect(persisted).not.toHaveProperty('leftAutoHidden')

    await setContainerWidth(wrapper, 700)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: true,
      leftAutoHidden: true
    })

    await setContainerWidth(wrapper, 1000)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: true,
      leftAutoHidden: false
    })

    await setContainerWidth(wrapper, 1500)
    expect(wrapper.find('.workbench-pane--right').exists()).toBe(true)
    expect(layoutState(wrapper).rightAutoHidden).toBe(false)
    wrapper.unmount()

    const reloaded = mountLayout()
    await setContainerWidth(reloaded, 1500)
    expect(reloaded.find('.workbench-pane--right').exists()).toBe(true)
    reloaded.unmount()
  })

  it('supports keyboard resize and double-click reset on resize handles', async () => {
    const wrapper = mountLayout()
    const leftHandle = wrapper.find('.workbench-resize-handle--left')

    await leftHandle.trigger('keydown', { key: 'ArrowRight' })
    expect(leftHandle.attributes('aria-valuenow')).toBe('328')

    await leftHandle.trigger('dblclick')
    expect(leftHandle.attributes('aria-valuenow')).toBe('320')
    wrapper.unmount()
  })
})
