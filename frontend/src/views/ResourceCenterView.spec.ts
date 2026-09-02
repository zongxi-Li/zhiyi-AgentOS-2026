import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import ResourceCenterView from './ResourceCenterView.vue'

const layoutStub = { template: '<div class="layout-stub"><slot name="main" /></div>' }
const routerLinkStub = {
  props: ['to'],
  template: '<a :href="typeof to === \'string\' ? to : to.path"><slot /></a>'
}

describe('ResourceCenterView', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders ResourceService health as unknown without inventing availability metrics', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({
      total: 1,
      items: [{
        profile: {
          resourceId: 'native_general_agent', resourceType: 'agent', deploymentTier: 'edge', capabilities: ['general'], domains: [],
          labels: {}, costMetadata: {}, capacity: 2, enabled: true, metadata: {}, version: 1
        },
        snapshot: {
          resourceId: 'native_general_agent', observedAt: '2026-08-29T00:00:00Z', availableSlots: 2,
          utilization: 0, healthStatus: 'unknown', metrics: {}
        },
        snapshotVersion: 1
      }]
    })

    const wrapper = mount(ResourceCenterView, {
      global: { stubs: { WorkbenchLayout: layoutStub, 'el-icon': true, 'router-link': routerLinkStub } }
    })
    await flushPromises()

    expect(wrapper.find('.resource-row').text()).toContain('边缘')
    expect(wrapper.find('.resource-row').text()).toContain('Unknown / 未知')
    expect(wrapper.find('.resource-row').text()).toContain('2 / 2')
    expect(wrapper.text()).not.toContain('Online')
    expect(wrapper.text()).not.toContain('GPU')
    expect(wrapper.text()).not.toContain('utilization')
  })

  it('shows an empty state when ResourceService has no profiles', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })

    const wrapper = mount(ResourceCenterView, {
      global: { stubs: { WorkbenchLayout: layoutStub, 'el-icon': true, 'router-link': routerLinkStub } }
    })
    await flushPromises()

    expect(wrapper.find('.resource-center__state').text()).toContain('暂无已登记 Resource')
  })

  it('groups resource center, federation, and model management under resource navigation', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })

    const wrapper = mount(ResourceCenterView, {
      global: { stubs: { WorkbenchLayout: layoutStub, 'el-icon': true, 'router-link': routerLinkStub } }
    })
    await flushPromises()

    const links = wrapper.findAll('.resource-center__nav a')
    expect(links).toHaveLength(3)
    expect(links.map(link => link.text())).toEqual(['资源中心', '联邦管理', '模型管理'])
    expect(links.map(link => link.attributes('href'))).toEqual(['/agentos/resources', '/federated-learning', '/federated-models'])
  })
})
