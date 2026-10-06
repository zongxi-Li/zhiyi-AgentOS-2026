import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi, type RuntimeResourceItem } from '@/services/api/agentos'
import ResourceOverviewPanel from './ResourceOverviewPanel.vue'
import ResourceDetailPanel from './ResourceDetailPanel.vue'
import ResourceRegistrationDialog from './ResourceRegistrationDialog.vue'

afterEach(() => vi.restoreAllMocks())
const item = (id: string, placement: string): RuntimeResourceItem => ({
  profile: { resourceId: id, resourceType: 'worker', runtimeKind: 'execution_backend', nodeId: 'node-1',
    deploymentTier: placement, capabilities: ['exec.agents'], domains: [], enabled: true, capacity: 2, version: 1,
    computeCapacity: { cpuCores: 0, memoryMb: 0, gpuMemoryMb: 0 } },
  snapshot: { healthStatus: 'unknown' }, snapshotVersion: 1
})
const stubs = { 'el-icon': true, 'el-drawer': true }

describe('resource plane adaptation', () => {
  it('renders device and unknown placements without dropping rows or inventing compute', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [item('embedded', 'device'), item('future', 'satellite')], total: 2 })
    vi.spyOn(agentosApi, 'listNodes').mockResolvedValue({ items: [], total: 0 })
    const wrapper = mount(ResourceOverviewPanel, { global: { stubs } })
    await flushPromises()
    expect(wrapper.findAll('.resource-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('本机设备')
    expect(wrapper.text()).toContain('其他位置 · satellite')
    expect(wrapper.find('.resource-summary__metric--compute').text()).toContain('未观测')
    expect(wrapper.text()).not.toContain('0核')
    wrapper.unmount()
  })

  it('counts physical compute once even when multiple runtimes share a node', async () => {
    const a = item('a', 'device'); a.profile.computeCapacity = { cpuCores: 8, memoryMb: 16384 }
    const b = item('b', 'device'); b.profile.computeCapacity = { cpuCores: 8, memoryMb: 16384 }
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [a, b], total: 2 })
    vi.spyOn(agentosApi, 'listNodes').mockResolvedValue({ items: [], total: 0 })
    const wrapper = mount(ResourceOverviewPanel, { global: { stubs } })
    await flushPromises()
    expect(wrapper.find('.resource-summary__metric--compute').text()).toContain('8核')
    expect(wrapper.find('.resource-summary__metric--compute').text()).not.toContain('16核')
    wrapper.unmount()
  })

  it('keeps resource rows when the node catalog is unavailable', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [item('a', 'device')], total: 1 })
    vi.spyOn(agentosApi, 'listNodes').mockRejectedValue(new Error('offline'))
    const wrapper = mount(ResourceOverviewPanel, { global: { stubs } })
    await flushPromises()
    expect(wrapper.findAll('.resource-row')).toHaveLength(1)
    expect(wrapper.text()).toContain('服务目录仍可单独查看')
    wrapper.unmount()
  })

  it('does not send runtime commands for a model endpoint', async () => {
    const model = item('endpoint-1', 'cloud'); model.profile.runtimeKind = 'model_endpoint'
    model.profile.provider = 'provider'; model.profile.model = 'model'; model.profile.contextWindowTokens = 8192
    const usage = vi.spyOn(agentosApi, 'listResourceUsage')
    const wrapper = mount(ResourceDetailPanel, { props: { item: model }, global: { stubs: { 'el-icon': true, 'el-switch': true, 'router-link': true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('8192 tokens')
    expect(wrapper.find('el-switch-stub').exists()).toBe(false)
    expect(usage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('registers a node with the new contract and keeps the one-time secret until acknowledged', async () => {
    vi.spyOn(agentosApi, 'listNodes').mockResolvedValue({ items: [], total: 0 })
    const register = vi.spyOn(agentosApi, 'registerNode').mockResolvedValue({ nodeId: 'node:edge:new', credentialId: 'nc-1', secret: 'one-time-secret', ownerScope: 'scope' })
    const wrapper = mount(ResourceRegistrationDialog, { props: { modelValue: false }, global: { stubs: { 'el-icon': true,
      'el-dialog': { template: '<div><slot name="header" /><slot /><slot name="footer" /></div>' } } } })
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    await wrapper.findAll('input')[0].setValue('node:edge:new')
    await wrapper.findAll('input')[2].setValue('scope')
    await wrapper.get('.rr-submit').trigger('click'); await flushPromises()
    expect(register.mock.calls[0][0]).toMatchObject({ profile: { nodeId: 'node:edge:new', placement: 'edge', ownerScope: 'scope' }, snapshot: { nodeId: 'node:edge:new', healthStatus: 'offline' } })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('one-time-secret')
    expect(wrapper.emitted('registered')).toBeUndefined()
    await wrapper.get('.rr-submit').trigger('click')
    expect(wrapper.emitted('registered')).toHaveLength(1)
    wrapper.unmount()
  })

  it('registers a runtime with its host placement and trust rather than the legacy agent profile', async () => {
    vi.spyOn(agentosApi, 'listNodes').mockResolvedValue({ items: [{ profile: { nodeId: 'node:edge:1',
      displayName: 'Edge', placement: 'edge', trust: 'sandboxed', ownerScope: 'scope', enabled: true },
      healthStatus: 'offline', snapshotVersion: 1 }], total: 1 })
    const register = vi.spyOn(agentosApi, 'registerResource').mockResolvedValue({ resourceId: 'runtime:1', credentialId: 'rc-1', secret: 'one-time', ownerScope: 'scope' })
    const wrapper = mount(ResourceRegistrationDialog, { props: { modelValue: true }, global: { stubs: {
      'el-icon': true, 'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
      'el-select': { name: 'ElSelect', props: ['modelValue'], template: '<div />' }
    } } })
    await flushPromises()
    await wrapper.findAll('.rr-type')[1].trigger('click')
    await wrapper.findAll('input')[0].setValue('runtime:1')
    await wrapper.findAll('select')[0].setValue('node:edge:1')
    wrapper.findAllComponents({ name: 'ElSelect' })[0].vm.$emit('update:modelValue', ['exec.research'])
    await wrapper.findAll('input')[2].setValue('https://worker.example.com')
    await wrapper.get('.rr-submit').trigger('click'); await flushPromises()
    expect(register.mock.calls[0][0]).toMatchObject({ profile: { runtimeId: 'runtime:1', nodeId: 'node:edge:1',
      kind: 'execution_backend', placement: 'edge', trust: 'sandboxed', ownerScope: 'scope',
      capabilities: ['exec.research'], endpoint: { protocol: 'https', address: 'https://worker.example.com' } },
      snapshot: { runtimeId: 'runtime:1', healthStatus: 'unknown' } })
    expect(register.mock.calls[0][0].profile).not.toHaveProperty('resourceType')
    wrapper.unmount()
  })
})
