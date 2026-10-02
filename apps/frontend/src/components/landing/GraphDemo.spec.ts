import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import GraphDemo from './GraphDemo.vue'

describe('GraphDemo (ACG graph)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the compiled graph with nodes and edges', () => {
    const wrapper = mount(GraphDemo, { props: { active: false } })

    expect(wrapper.find('[data-testid="acg-graph-demo"]').exists()).toBe(true)
    expect(wrapper.findAll('.graph-demo__node')).toHaveLength(6)
    expect(wrapper.findAll('.graph-demo__edge')).toHaveLength(6)
    expect(wrapper.get('.graph-demo__status').text()).toContain('图已编译')
    expect(wrapper.find('.graph-demo').classes()).not.toContain('is-live')
    expect(wrapper.text()).toContain('Planner 规划')
    expect(wrapper.text()).toContain('outputRef')
  })

  it('goes live only when the section is active and motion is allowed', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const live = mount(GraphDemo, { props: { active: true } })
    expect(live.find('.graph-demo').classes()).toContain('is-live')
    expect(live.get('.graph-demo__status').text()).toContain('组网运行中')
    live.unmount()

    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    const reduced = mount(GraphDemo, { props: { active: true, dark: true } })
    expect(reduced.find('.graph-demo').classes()).not.toContain('is-live')
    reduced.unmount()
  })

  it('highlights the hovered node and its connected edges', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    const wrapper = mount(GraphDemo, { props: { active: false } })

    const planner = wrapper.findAll('.graph-demo__node')[1]
    await planner.trigger('mouseenter')
    expect(wrapper.find('.graph-demo').classes()).not.toContain('is-live')
    expect(wrapper.findAll('.graph-demo__edge.is-hot')).toHaveLength(3)
    expect(wrapper.findAll('.graph-demo__node.is-hot')).toHaveLength(1)

    await planner.trigger('mouseleave')
    expect(wrapper.findAll('.graph-demo__edge.is-hot')).toHaveLength(0)
  })
})
