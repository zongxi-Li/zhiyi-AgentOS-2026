import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppTopBar from './AppTopBar.vue'

const mountTopBar = () => mount(AppTopBar, {
  props: {
    contextEyebrow: 'Projects',
    contextTitle: 'Mission Workspace',
    contextMeta: 'Run run_1234567890'
  },
  global: {
    stubs: {
      'el-icon': { template: '<span><slot /></span>' }
    }
  }
})

describe('AppTopBar', () => {
  it('renders the shell context and command center', () => {
    const wrapper = mountTopBar()

    expect(wrapper.find('[aria-label="应用工作栏"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Mission Workspace')
    expect(wrapper.text()).toContain('Run run_1234567890')
    expect(wrapper.get('input').attributes('placeholder')).toBe('搜索任务、步骤、运行或命令')
  })

  it('emits shell actions and clears the command on Escape', async () => {
    const wrapper = mountTopBar()

    await wrapper.get('[aria-label="打开导航"]').trigger('click')
    await wrapper.find('.app-topbar__menu-links button').trigger('click')
    await wrapper.get('input').setValue('trace')
    await wrapper.get('input').trigger('keydown.esc')

    expect(wrapper.emitted('menu')).toHaveLength(1)
    expect(wrapper.emitted('navigate')).toEqual([['/agentos/acg']])
    expect(wrapper.get('input').element).toHaveProperty('value', '')
  })

  it('removes the requested topbar action group', () => {
    const wrapper = mountTopBar()

    expect(wrapper.find('.app-topbar__actions').exists()).toBe(false)
    expect(wrapper.find('[aria-label="切换布局"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="打开设置"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="打开用户中心"]').exists()).toBe(false)
  })
})
