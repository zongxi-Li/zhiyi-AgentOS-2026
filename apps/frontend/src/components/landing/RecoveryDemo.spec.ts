import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RecoveryDemo from './RecoveryDemo.vue'

describe('RecoveryDemo (trace waterfall)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const spansOn = (wrapper: ReturnType<typeof mount>) =>
    wrapper.findAll('.recovery-demo__span.is-on').map(node => node.classes().find(c => c.startsWith('is-') && c !== 'is-on'))
  const tickerText = (wrapper: ReturnType<typeof mount>) => wrapper.get('.recovery-demo__ticker').text()

  it('renders the completed waterfall when not playing', () => {
    const wrapper = mount(RecoveryDemo, { props: { active: false } })

    expect(wrapper.find('[data-testid="recovery-run-demo"]').exists()).toBe(true)
    expect(wrapper.findAll('.recovery-demo__lane')).toHaveLength(3)
    expect(wrapper.findAll('.recovery-demo__span')).toHaveLength(5)
    expect(spansOn(wrapper)).toEqual(['is-done', 'is-fault', 'is-run', 'is-patch', 'is-done'])
    expect(wrapper.get('.recovery-demo__status').text()).toContain('已恢复交付')
    expect(tickerText(wrapper)).toContain('Review barrier · 交付')
    expect(wrapper.get('.recovery-demo__playhead').attributes('style')).toContain('1.0000')
    expect(wrapper.find('.recovery-demo__gap-hint').exists()).toBe(true)
    expect(wrapper.text()).toContain('Checkpoint')
    expect(wrapper.text()).toContain('GraphPatch')
  })

  it('advances spans, playhead and ticker while the section is active', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const wrapper = mount(RecoveryDemo, { props: { active: true } })

    expect(wrapper.find('.recovery-demo').classes()).toContain('is-live')
    expect(spansOn(wrapper)).toEqual(['is-done'])
    expect(tickerText(wrapper)).toContain('Checkpoint CAS 快照')
    expect(wrapper.get('.recovery-demo__status').text()).toContain('快照中')

    await vi.advanceTimersByTimeAsync(2000)
    expect(spansOn(wrapper)).toEqual(['is-done', 'is-fault'])
    expect(wrapper.get('.recovery-demo__status').text()).toContain('节点中断')
    expect(tickerText(wrapper)).toContain('节点失效 · 模型超时')

    await vi.advanceTimersByTimeAsync(3000)
    expect(spansOn(wrapper)).toEqual(['is-done', 'is-fault', 'is-patch'])
    expect(wrapper.find('.recovery-demo').classes()).toContain('is-live')
    expect(tickerText(wrapper)).toContain('alternate rebind · 写作节点')
    expect(wrapper.get('.recovery-demo__status').text()).toContain('恢复中')

    await vi.advanceTimersByTimeAsync(4000)
    expect(spansOn(wrapper)).toEqual(['is-done', 'is-fault', 'is-run', 'is-patch', 'is-done'])
    expect(tickerText(wrapper)).toContain('Evidence 复核通过')
    expect(wrapper.get('.recovery-demo__status').text()).toContain('恢复中')

    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.get('.recovery-demo__status').text()).toContain('已恢复交付')
    expect(tickerText(wrapper)).toContain('Review barrier · 交付')
  })

  it('freezes on the recovered waterfall when the visitor prefers reduced motion', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    const wrapper = mount(RecoveryDemo, { props: { active: true } })

    expect(wrapper.find('.recovery-demo').classes()).not.toContain('is-live')
    expect(spansOn(wrapper)).toEqual(['is-done', 'is-fault', 'is-run', 'is-patch', 'is-done'])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('stops and resets the loop when deactivated', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const wrapper = mount(RecoveryDemo, { props: { active: true } })
    expect(vi.getTimerCount()).toBe(1)

    await wrapper.setProps({ active: false })
    expect(vi.getTimerCount()).toBe(0)
    expect(wrapper.find('.recovery-demo').classes()).not.toContain('is-live')
    expect(wrapper.get('.recovery-demo__status').text()).toContain('已恢复交付')

    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
