import { nextTick } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WorkbenchVerticalSplit from './WorkbenchVerticalSplit.vue'

const STORAGE_KEY = 'test.workbench.vertical-split'

const mountSplit = () => mount(WorkbenchVerticalSplit, {
  props: {
    storageKey: STORAGE_KEY,
    defaultHeight: 260,
    minHeight: 120,
    minGraphHeight: 280
  },
  slots: {
    graph: '<div class="graph-slot">graph</div>',
    bottom: '<div class="bottom-slot">bottom</div>'
  }
})

const handle = (wrapper: VueWrapper) => wrapper.find('.workbench-horizontal-resize-handle')

describe('WorkbenchVerticalSplit', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps the graph, horizontal handle and bottom panel as sibling layout nodes', () => {
    const wrapper = mountSplit()
    const children = Array.from(wrapper.find('.workbench-vertical-split').element.children)
      .map(element => element.className)

    expect(children).toEqual([
      'workbench-vertical-split__graph-pane',
      'workbench-horizontal-resize-handle',
      'workbench-vertical-split__bottom-panel'
    ])
    expect(handle(wrapper).attributes('aria-valuenow')).toBe('260')
    wrapper.unmount()
  })

  it('resizes only from the horizontal handle, clamps, persists and cleans up pointer state', async () => {
    const wrapper = mountSplit()
    const resizeHandle = handle(wrapper)

    await resizeHandle.trigger('pointerdown', { button: 0, clientY: 500, pointerId: 1 })
    expect(document.body.style.cursor).toBe('row-resize')
    expect(document.body.style.userSelect).toBe('none')

    await resizeHandle.trigger('pointermove', { clientY: 400, pointerId: 1 })
    await vi.advanceTimersByTimeAsync(20)
    await nextTick()
    expect(resizeHandle.attributes('aria-valuenow')).toBe('360')

    await resizeHandle.trigger('pointermove', { clientY: 900, pointerId: 1 })
    await vi.advanceTimersByTimeAsync(20)
    await nextTick()
    expect(resizeHandle.attributes('aria-valuenow')).toBe('120')

    await resizeHandle.trigger('pointercancel', { pointerId: 1 })
    expect(document.body.style.cursor).toBe('')
    expect(document.body.style.userSelect).toBe('')
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')).toMatchObject({ bottomPanelHeight: 120 })

    const vm = wrapper.vm as unknown as { setCollapsed: (value: boolean) => void }
    vm.setCollapsed(true)
    await nextTick()
    expect(handle(wrapper).exists()).toBe(false)
    expect(wrapper.find('.workbench-vertical-split__bottom-panel').exists()).toBe(true)
    vm.setCollapsed(false)
    await nextTick()
    expect(handle(wrapper).attributes('aria-valuenow')).toBe('120')
    wrapper.unmount()
  })

  it('restores the user panel height and collapsed state from layout persistence', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      bottomPanelHeight: 340,
      bottomPanelCollapsedByUser: true,
      runId: 'must-not-be-used'
    }))
    const wrapper = mountSplit()

    expect(handle(wrapper).exists()).toBe(false)
    expect(wrapper.find('.workbench-vertical-split').classes()).toContain('is-collapsed')
    wrapper.unmount()
  })

  it('can start collapsed when the host provides a default state', () => {
    const wrapper = mount(WorkbenchVerticalSplit, {
      props: { storageKey: STORAGE_KEY, defaultCollapsed: true },
      slots: { graph: '<div />', bottom: '<div />' }
    })

    expect(wrapper.find('.workbench-vertical-split').classes()).toContain('is-collapsed')
    expect(handle(wrapper).exists()).toBe(false)
    wrapper.unmount()
  })
})
