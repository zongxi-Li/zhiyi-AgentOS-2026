import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkbenchStatusBar from './WorkbenchStatusBar.vue'

const tabs = [
  { id: 'problems', label: 'Problems', count: 0, tone: 'failed' as const },
  { id: 'communication', label: 'Communication', count: 69 }
]

describe('WorkbenchStatusBar', () => {
  it('emits the selected tab and keeps zero counts free of the alert style', async () => {
    const wrapper = mount(WorkbenchStatusBar, {
      props: { tabs, modelValue: 'communication', collapsed: false }
    })

    expect(wrapper.find('.workbench-status-bar__tab.active').text()).toContain('Communication')
    expect(wrapper.findAll('.workbench-status-bar__tab-count.is-alert')).toHaveLength(0)

    await wrapper.findAll('.workbench-status-bar__tab')[0].trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['problems'])
    wrapper.unmount()
  })

  it('alerts failed-tone counts only while count > 0 and emits toggle', async () => {
    const wrapper = mount(WorkbenchStatusBar, {
      props: { tabs: [{ ...tabs[0], count: 3 }, tabs[1]], modelValue: 'problems', collapsed: true }
    })

    expect(wrapper.find('.workbench-status-bar__tab-count.is-alert').text()).toBe('3')
    expect(wrapper.find('.workbench-status-bar__toggle').attributes('aria-expanded')).toBe('false')

    await wrapper.find('.workbench-status-bar__toggle').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
    wrapper.unmount()
  })

  it('renders the left-corner run identity with a semantic status dot', () => {
    const wrapper = mount(WorkbenchStatusBar, {
      props: { tabs, modelValue: 'communication', collapsed: false, runId: 'run_8a53fc4c67e5', runStatus: 'succeeded', historical: true }
    })

    expect(wrapper.find('.workbench-status-bar__run-id').text()).toBe('Run run_8a53fc4c67e5')
    expect(wrapper.find('.workbench-status-bar__run-dot').attributes('style')).toContain('var(--sem-success)')
    expect(wrapper.find('.workbench-status-bar__run-mode').text()).toBe('read-only')
    wrapper.unmount()
  })

  it('omits the run block when no run is bound', () => {
    const wrapper = mount(WorkbenchStatusBar, {
      props: { tabs, modelValue: 'communication', collapsed: false }
    })

    expect(wrapper.find('.workbench-status-bar__run').exists()).toBe(false)
    wrapper.unmount()
  })

  it('opens the run picker, emits select-run and rerun like the VS Code branch picker', async () => {
    const wrapper = mount(WorkbenchStatusBar, {
      props: {
        tabs,
        modelValue: 'problems',
        collapsed: false,
        runId: 'run_2',
        runStatus: 'running',
        runs: [{ runId: 'run_1', status: 'succeeded' }, { runId: 'run_2', status: 'running' }],
        canRerun: true,
        rerunPending: false,
        rerunDisabledReason: '',
        rerunLabel: '再次运行'
      }
    })

    expect(wrapper.find('.workbench-status-bar__run-picker').exists()).toBe(false)
    await wrapper.find('.workbench-status-bar__run-trigger').trigger('click')
    expect(wrapper.find('.workbench-status-bar__run-picker').exists()).toBe(true)

    const items = wrapper.findAll('.workbench-status-bar__run-item')
    expect(items[0].text()).toContain('run_2')
    expect(items[0].classes()).toContain('is-current')
    await items[0].trigger('click')
    expect(wrapper.emitted('select-run')).toEqual([['run_2']])
    expect(wrapper.find('.workbench-status-bar__run-picker').exists()).toBe(false)

    await wrapper.find('.workbench-status-bar__run-trigger').trigger('click')
    await wrapper.find('.workbench-status-bar__run-action').trigger('click')
    expect(wrapper.emitted('rerun')).toHaveLength(1)
    wrapper.unmount()
  })

  it('disables rerun while the selected run is still active', async () => {
    const wrapper = mount(WorkbenchStatusBar, {
      props: {
        tabs,
        modelValue: 'problems',
        collapsed: false,
        runId: 'run_2',
        runs: [{ runId: 'run_2', status: 'running' }],
        canRerun: false,
        rerunDisabledReason: '当前运行尚未结束'
      }
    })

    await wrapper.find('.workbench-status-bar__run-trigger').trigger('click')
    const action = wrapper.find('.workbench-status-bar__run-action')
    expect((action.element as HTMLButtonElement).disabled).toBe(true)
    expect(action.attributes('title')).toContain('当前运行尚未结束')
    await action.trigger('click')
    expect(wrapper.emitted('rerun')).toBeUndefined()
    wrapper.unmount()
  })
})
