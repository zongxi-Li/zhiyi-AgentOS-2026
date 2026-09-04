import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { agentosApi } from '@/services/api/agentos'
import ResourceCenterView from './ResourceCenterView.vue'

const layoutStub = { template: '<div class="layout-stub"><slot name="main" /></div>' }

const createTestRouter = async () => {
  const testRouter = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agentos/resources', component: ResourceCenterView }]
  })
  await testRouter.push('/agentos/resources')
  await testRouter.isReady()
  return testRouter
}

describe('ResourceCenterView', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders ResourceService health as unknown without inventing availability metrics', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({
      total: 1,
      items: [{
        profile: {
          resourceId: 'native_general_agent', resourceType: 'agent', capabilities: ['general'], domains: [],
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
      global: { plugins: [await createTestRouter(), createPinia()], stubs: { WorkbenchLayout: layoutStub, 'el-icon': true } }
    })
    await flushPromises()

    expect(wrapper.find('.resource-row').text()).toContain('Unknown / 未知')
    expect(wrapper.find('.resource-row').text()).toContain('2 / 2')
    expect(wrapper.text()).not.toContain('Online')
    expect(wrapper.text()).not.toContain('GPU')
    expect(wrapper.text()).not.toContain('utilization')
  })

  it('shows an empty state when ResourceService has no profiles', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })

    const wrapper = mount(ResourceCenterView, {
      global: { plugins: [await createTestRouter(), createPinia()], stubs: { WorkbenchLayout: layoutStub, 'el-icon': true } }
    })
    await flushPromises()

    expect(wrapper.find('.resource-state').text()).toContain('暂无已登记 Resource')
  })

  it('switches between resource tabs and synchronizes the selected tab to the URL', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agentos/resources', component: ResourceCenterView }]
    })
    await testRouter.push('/agentos/resources')
    await testRouter.isReady()

    const wrapper = mount(ResourceCenterView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          WorkbenchLayout: layoutStub,
          RoleManagementPanel: { template: '<div data-testid="role-management-panel-stub" />' },
          'el-icon': true
        }
      }
    })

    expect(wrapper.text()).toContain('资源概览')
    expect(wrapper.text()).toContain('角色管理')
    expect(wrapper.text()).toContain('联邦管理')
    expect(wrapper.text()).toContain('模型管理')
    await wrapper.get('[data-testid="resource-tab-roles"]').trigger('click')
    await flushPromises()

    expect(testRouter.currentRoute.value.path).toBe('/agentos/resources')
    expect(testRouter.currentRoute.value.query.tab).toBe('roles')
  })
})
