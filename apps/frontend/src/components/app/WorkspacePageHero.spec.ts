import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkspacePageHero from './WorkspacePageHero.vue'

describe('WorkspacePageHero', () => {
  it('renders a semantic text title and action slot', () => {
    const wrapper = mount(WorkspacePageHero, {
      props: {
        eyebrow: 'RESOURCE CENTER',
        title: '资源中心',
        description: '资源描述'
      },
      slots: { actions: '<button>刷新</button>' }
    })

    expect(wrapper.find('h1').text()).toBe('资源中心')
    expect(wrapper.text()).toContain('RESOURCE CENTER')
    expect(wrapper.text()).toContain('资源描述')
    expect(wrapper.text()).toContain('刷新')
    expect(wrapper.find('img').exists()).toBe(false)
  })
})
