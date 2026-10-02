import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MissionRunDemo from './MissionRunDemo.vue'

describe('MissionRunDemo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const stateTexts = (wrapper: ReturnType<typeof mount>) =>
    wrapper.findAll('.mission-demo__step-state').map(node => node.text())

  it('renders the static delivered state when not playing', () => {
    const wrapper = mount(MissionRunDemo, { props: { active: false } })

    expect(wrapper.find('[data-testid="mission-run-demo"]').exists()).toBe(true)
    expect(stateTexts(wrapper)).toEqual(['完成', '完成', '完成', '完成', '完成'])
    expect(wrapper.get('.mission-demo__status').text()).toContain('交付完成')
    expect(wrapper.findAll('.mission-demo__event.is-shown')).toHaveLength(8)
    expect(wrapper.text()).toContain('Checkpoint CAS')
    expect(wrapper.text()).toContain('GraphPatch')
  })

  it('animates the mission timeline while the section is active', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const wrapper = mount(MissionRunDemo, { props: { active: true } })

    expect(stateTexts(wrapper)).toEqual(['运行中', '排队', '排队', '排队', '排队'])
    expect(wrapper.get('.mission-demo__status').text()).toContain('规划中')

    await vi.advanceTimersByTimeAsync(4000)
    expect(stateTexts(wrapper)).toEqual(['完成', '运行中', '运行中', '排队', '排队'])
    expect(wrapper.get('.mission-demo__status').text()).toContain('运行中')
    expect(wrapper.text()).toContain('并行 superstep 启动')

    await vi.advanceTimersByTimeAsync(7000)
    expect(stateTexts(wrapper)).toEqual(['完成', '完成', '完成', '完成', '运行中'])

    await vi.advanceTimersByTimeAsync(800)
    expect(wrapper.get('.mission-demo__status').text()).toContain('交付完成')
    expect(wrapper.findAll('.mission-demo__event.is-shown')).toHaveLength(8)
  })

  it('freezes on the delivered state when the visitor prefers reduced motion', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    const wrapper = mount(MissionRunDemo, { props: { active: true } })

    expect(stateTexts(wrapper)).toEqual(['完成', '完成', '完成', '完成', '完成'])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('stops and clears the loop when deactivated', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const wrapper = mount(MissionRunDemo, { props: { active: true } })
    expect(vi.getTimerCount()).toBe(1)

    await wrapper.setProps({ active: false })
    expect(vi.getTimerCount()).toBe(0)
    expect(stateTexts(wrapper)).toEqual(['完成', '完成', '完成', '完成', '完成'])

    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
