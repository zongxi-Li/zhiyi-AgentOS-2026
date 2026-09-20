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
    right: (state: Record<string, any>) => h('div', { class: 'slot-right' }, [
      h('span', { class: 'right-maximized-state' }, String(state.rightPaneMaximized)),
      h('button', { class: 'toggle-right-maximized', onClick: state.toggleRightPaneMaximized }, 'maximize'),
      h('button', { class: 'toggle-right', onClick: state.toggleRightPane }, 'close')
    ]),
    main: (state: Record<string, unknown>) => h('div', { class: 'slot-main' }, [
      h('span', { class: 'layout-state' }, JSON.stringify({
        leftAutoHidden: state.leftAutoHidden,
        rightAutoHidden: state.rightAutoHidden,
        rightPaneVisible: state.rightPaneVisible
      })),
      h('button', { class: 'toggle-right', onClick: state.toggleRightPane }, 'toggle')
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
  rightPaneVisible: boolean
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

  it('keeps both panes visible as the workbench becomes compact', async () => {
    const wrapper = mountLayout()

    await setContainerWidth(wrapper, 1000)
    expect(wrapper.find('.workbench-pane--right').exists()).toBe(true)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: false,
      leftAutoHidden: false
    })
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>
    expect(persisted).not.toHaveProperty('rightAutoHidden')
    expect(persisted).not.toHaveProperty('leftAutoHidden')

    await setContainerWidth(wrapper, 700)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: false,
      leftAutoHidden: false,
      rightPaneVisible: true
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

  it('toggles the right inspector without persisting the manual visibility state', async () => {
    const wrapper = mountLayout()

    expect(wrapper.find('.workbench-pane--right').exists()).toBe(true)
    await wrapper.find('.toggle-right').trigger('click')
    await nextTick()
    expect(wrapper.find('.workbench-pane--right').exists()).toBe(false)
    expect(layoutState(wrapper).rightPaneVisible).toBe(false)

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>
    expect(persisted).not.toHaveProperty('rightCollapsedByUser')

    await wrapper.find('.toggle-right').trigger('click')
    await nextTick()
    expect(wrapper.find('.workbench-pane--right').exists()).toBe(true)
    expect(layoutState(wrapper).rightPaneVisible).toBe(true)
    wrapper.unmount()
  })

  it('maximizes the Inspector and restores the three-pane workbench', async () => {
    const wrapper = mountLayout()

    expect(wrapper.find('.workbench-pane--left').isVisible()).toBe(true)
    expect(wrapper.find('.workbench-pane--main').isVisible()).toBe(true)
    expect(wrapper.find('.right-maximized-state').text()).toBe('false')

    await wrapper.find('.toggle-right-maximized').trigger('click')
    await nextTick()

    expect(wrapper.find('.workbench-layout').classes()).toContain('is-right-maximized')
    expect(wrapper.find('.workbench-pane--left').exists()).toBe(false)
    expect(wrapper.find('.workbench-pane--main').attributes('style')).toContain('display: none')
    expect(wrapper.find('.workbench-pane--right').isVisible()).toBe(true)
    expect(wrapper.find('.right-maximized-state').text()).toBe('true')

    await wrapper.find('.toggle-right-maximized').trigger('click')
    await nextTick()

    expect(wrapper.find('.workbench-layout').classes()).not.toContain('is-right-maximized')
    expect(wrapper.find('.workbench-pane--left').isVisible()).toBe(true)
    expect(wrapper.find('.workbench-pane--main').isVisible()).toBe(true)
    wrapper.unmount()
  })

  it('keeps the compact Inspector default while allowing deliberate widening', async () => {
    const originalViewportWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1600 })
    try {
      const wrapper = mount(WorkbenchLayout, {
        props: {
          storageKey: STORAGE_KEY,
          rightPaneMinWidth: 280,
          rightPaneDefaultWidth: 320,
          rightPaneMaxWidth: 520
        },
        slots: {
          left: '<div>left</div>',
          main: '<div>main</div>',
          right: '<div>inspector</div>'
        }
      })

      const handle = wrapper.find('.workbench-resize-handle--right')
      expect(handle.attributes('aria-valuemin')).toBe('280')
      expect(handle.attributes('aria-valuenow')).toBe('320')
      expect(handle.attributes('aria-valuemax')).toBe('520')
      expect(wrapper.find('.workbench-layout').attributes('style')).toContain('--workbench-right-max-width: 520px')
      await handle.trigger('keydown', { key: 'End' })
      expect(handle.attributes('aria-valuenow')).toBe('520')
      wrapper.unmount()
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalViewportWidth })
    }
  })

  it('manually collapses and reopens the inspector without affecting the left pane', async () => {
    const wrapper = mountLayout()

    await setContainerWidth(wrapper, 1000)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: false,
      leftAutoHidden: false,
       rightPaneVisible: true
    })

    await wrapper.find('.toggle-right').trigger('click')
    await nextTick()

    expect(wrapper.find('.workbench-pane--right').exists()).toBe(false)
    expect(wrapper.find('.workbench-pane--left').exists()).toBe(true)
    expect(layoutState(wrapper)).toMatchObject({
      rightAutoHidden: false,
      leftAutoHidden: false,
      rightPaneVisible: false
    })

    await wrapper.find('.toggle-right').trigger('click')
    await nextTick()
    expect(wrapper.find('.workbench-pane--right').exists()).toBe(true)
    expect(wrapper.find('.workbench-pane--left').exists()).toBe(true)

    wrapper.unmount()
  })

  it('mounts the optional bottom-panel slot inside the shared vertical split', () => {
    const wrapper = mount(WorkbenchLayout, {
      props: {
        storageKey: STORAGE_KEY,
        showBottomPanel: true,
        bottomPanelStorageKey: `${STORAGE_KEY}.bottom`,
        bottomPanelDefaultCollapsed: true
      },
      slots: {
        main: '<div class="slot-main-content">main</div>',
        bottom: '<div class="slot-bottom">bottom</div>'
      }
    })

    expect(wrapper.find('.workbench-vertical-split').exists()).toBe(true)
    expect(wrapper.find('.slot-main-content').exists()).toBe(true)
    expect(wrapper.find('.slot-bottom').exists()).toBe(true)
    expect(wrapper.find('.workbench-vertical-split').classes()).toContain('is-collapsed')
    wrapper.unmount()
  })
})
