import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProviderDemo from './ProviderDemo.vue'

describe('ProviderDemo (status tiles)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const tileStates = (wrapper: ReturnType<typeof mount>) =>
    wrapper.findAll('.provider-demo__tile').map(node => node.classes().find(c => ['is-done', 'is-fault', 'is-queued', 'is-running'].includes(c)))
  const tileStateLabels = (wrapper: ReturnType<typeof mount>) =>
    wrapper.findAll('.provider-demo__tile-state').map(node => node.text().trim())
  const tickerText = (wrapper: ReturnType<typeof mount>) => wrapper.get('.provider-demo__ticker').text()

  it('renders the all-healthy status board when not playing', () => {
    const wrapper = mount(ProviderDemo, { props: { active: false } })

    expect(wrapper.find('[data-testid="provider-run-demo"]').exists()).toBe(true)
    expect(wrapper.findAll('.provider-demo__tile')).toHaveLength(3)
    expect(tileStates(wrapper)).toEqual(['is-done', 'is-done', 'is-done'])
    expect(tileStateLabels(wrapper)).toEqual(['健康', '健康', '健康'])
    expect(wrapper.get('.provider-demo__status').text()).toContain('全部健康')
    expect(tickerText(wrapper)).toContain('治理恢复 · 服务无感')
    expect(wrapper.find('.provider-demo__link.is-hot').exists()).toBe(false)
    expect(wrapper.get('.provider-demo__link span').text()).toBe('Failover')
    expect(wrapper.text()).toContain('版本协商 v2')
  })

  it('animates the failover between tiles while the section is active', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const wrapper = mount(ProviderDemo, { props: { active: true } })

    expect(tileStates(wrapper)).toEqual(['is-done', 'is-done', 'is-queued'])
    expect(tileStateLabels(wrapper)).toEqual(['健康', '健康', '待命'])
    expect(wrapper.get('.provider-demo__status').text()).toContain('治理中')

    await vi.advanceTimersByTimeAsync(2000)
    expect(tileStates(wrapper)).toEqual(['is-done', 'is-fault', 'is-queued'])
    expect(tileStateLabels(wrapper)).toEqual(['健康', '熔断', '待命'])
    expect(wrapper.get('.provider-demo__status').text()).toContain('故障转移中')
    expect(tickerText(wrapper)).toContain('心跳超时 · 熔断打开')

    await vi.advanceTimersByTimeAsync(2000)
    expect(tileStates(wrapper)).toEqual(['is-done', 'is-fault', 'is-running'])
    expect(tileStateLabels(wrapper)).toEqual(['健康', '熔断', '接管中'])
    expect(wrapper.find('.provider-demo__link.is-hot').exists()).toBe(true)
    expect(tickerText(wrapper)).toContain('Failover · 流量切至备模型')

    await vi.advanceTimersByTimeAsync(3000)
    expect(tickerText(wrapper)).toContain('Key rotation 完成')

    await vi.advanceTimersByTimeAsync(3000)
    expect(tileStates(wrapper)).toEqual(['is-done', 'is-fault', 'is-done'])
    expect(tileStateLabels(wrapper)).toEqual(['健康', '熔断', '健康'])
    expect(wrapper.get('.provider-demo__status').text()).toContain('全部健康')
    expect(wrapper.find('.provider-demo__link.is-hot').exists()).toBe(false)
  })

  it('freezes on the healthy board when the visitor prefers reduced motion', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    const wrapper = mount(ProviderDemo, { props: { active: true } })

    expect(tileStates(wrapper)).toEqual(['is-done', 'is-done', 'is-done'])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('stops and resets the board when deactivated', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const wrapper = mount(ProviderDemo, { props: { active: true } })
    expect(vi.getTimerCount()).toBe(1)

    await wrapper.setProps({ active: false })
    expect(vi.getTimerCount()).toBe(0)
    expect(tileStates(wrapper)).toEqual(['is-done', 'is-done', 'is-done'])
    expect(wrapper.get('.provider-demo__status').text()).toContain('全部健康')

    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
