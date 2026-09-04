import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkbenchBottomPanel from './WorkbenchBottomPanel.vue'

const tabs = [
  { id: 'result', label: '结果' },
  { id: 'trace', label: '运行轨迹', count: 2 }
]

describe('WorkbenchBottomPanel', () => {
  it('switches between real panel tabs and collapses without destroying the host', async () => {
    const wrapper = mount(WorkbenchBottomPanel, {
      props: { tabs },
      global: { stubs: { 'el-icon': { template: '<i><slot /></i>' } } },
      slots: {
        'tab-result': '<div class="result-slot">result</div>',
        'tab-trace': '<div class="trace-slot">trace</div>'
      }
    })

    expect(wrapper.find('.result-slot').exists()).toBe(true)
    expect(wrapper.find('.trace-slot').exists()).toBe(false)
    await wrapper.findAll('.workbench-bottom-panel__tab')[1].trigger('click')
    expect(wrapper.find('.trace-slot').exists()).toBe(true)

    await wrapper.find('.workbench-bottom-panel__collapse').trigger('click')
    await wrapper.setProps({ modelValue: true })
    expect(wrapper.find('.workbench-bottom-panel').exists()).toBe(true)
    expect(wrapper.find('.workbench-bottom-panel__body').exists()).toBe(false)
    expect(wrapper.find('.workbench-bottom-panel__collapse').attributes('aria-expanded')).toBe('false')
    await wrapper.find('.workbench-bottom-panel__collapse').trigger('click')
    await wrapper.setProps({ modelValue: false })
    expect(wrapper.find('.trace-slot').exists()).toBe(true)
    wrapper.unmount()
  })

  it('preserves the active tab through the optional panel storage key and supports a default slot', async () => {
    const storageKey = 'test.bottom-panel.active-tab'
    const wrapper = mount(WorkbenchBottomPanel, {
      props: { tabs, storageKey },
      global: { stubs: { 'el-icon': { template: '<i><slot /></i>' } } },
      slots: { default: '<div class="generic-slot">generic</div>' }
    })

    await wrapper.findAll('.workbench-bottom-panel__tab')[1].trigger('click')
    expect(localStorage.getItem(`${storageKey}.activeTab`)).toBe('trace')
    expect(wrapper.find('.generic-slot').exists()).toBe(true)
    wrapper.unmount()

    const reloaded = mount(WorkbenchBottomPanel, {
      props: { tabs, storageKey },
      global: { stubs: { 'el-icon': { template: '<i><slot /></i>' } } },
      slots: { default: '<div class="generic-slot">generic</div>' }
    })
    expect(reloaded.find('.trace-slot').exists()).toBe(false)
    expect(reloaded.find('.generic-slot').exists()).toBe(true)
    expect(reloaded.find('.workbench-bottom-panel__tab.active').text()).toContain('运行轨迹')
    reloaded.unmount()
  })
})
