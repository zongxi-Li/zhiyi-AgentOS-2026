import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { agentosApi } from '@/services/api/agentos'
import { federatedModelApi } from '@/services/api/federatedModel'
import { roleApi } from '@/services/api/role'
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
    expect(wrapper.find('.resource-row').text()).toContain('算力')
    expect(wrapper.find('.resource-row').text()).toContain('未观测')
    expect(wrapper.text()).not.toContain('Online')
    expect(wrapper.text()).not.toContain('GPU')
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
    expect(wrapper.text()).toContain('模型管理')
    await wrapper.get('[data-testid="resource-tab-roles"]').trigger('click')
    await flushPromises()

    expect(testRouter.currentRoute.value.path).toBe('/agentos/resources')
    expect(testRouter.currentRoute.value.query.tab).toBe('roles')
  })

  it('defaults to overview and follows browser query changes', async () => {
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
          RoleManagementPanel: { template: '<div data-testid="roles-panel" />' },
          ModelManagementPanel: { template: '<div data-testid="models-panel" />' },
          'el-icon': true
        }
      }
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="resource-tab-overview"]').classes()).toContain('active')

    await testRouter.push('/agentos/resources?tab=models')
    await flushPromises()

    expect(wrapper.get('[data-testid="resource-tab-models"]').classes()).toContain('active')
    expect(wrapper.find('[data-testid="models-panel"]').exists()).toBe(true)
  })

  it('normalizes an unknown tab query to the default URL', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agentos/resources', component: ResourceCenterView }]
    })
    await testRouter.push('/agentos/resources?tab=unknown')
    await testRouter.isReady()

    mount(ResourceCenterView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          WorkbenchLayout: layoutStub,
          ResourceOverviewPanel: { template: '<div />' },
          'el-icon': true
        }
      }
    })
    await flushPromises()

    expect(testRouter.currentRoute.value.fullPath).toBe('/agentos/resources')
  })

  it('renders the shared semantic hero and constrained page canvas', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })
    const wrapper = mount(ResourceCenterView, {
      global: { plugins: [await createTestRouter(), createPinia()], stubs: { WorkbenchLayout: layoutStub, 'el-icon': true } }
    })

    expect(wrapper.get('h1').text()).toBe('资源中心')
    expect(wrapper.get('.resource-center__main').attributes('data-max-width')).toBe('1400px')
  })

  it('keeps roles and model management wired to the existing stores and APIs', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(roleApi, 'getBuiltinRoles').mockResolvedValue([{
      id: 'role_builtin',
      name: '内置助手',
      description: '内置角色',
      systemPrompt: 'system prompt',
      isBuiltin: true
    }])
    vi.spyOn(roleApi, 'getCustomRoles').mockResolvedValue([])
    vi.spyOn(federatedModelApi, 'listModels').mockResolvedValue({
      success: true,
      data: {
        legal: {
          lawyer: {
            name: '律师Agent模型',
            version: '1.0.0',
            status: 'active',
            performance: { accuracy: 0.9, speed: 0.8, quality: 0.85 }
          }
        }
      }
    })
    const testRouter = await createTestRouter()
    const wrapper = mount(ResourceCenterView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          WorkbenchLayout: layoutStub,
          RoleCard: { props: ['role'], template: '<article class="role-card">{{ role.name }}</article>' },
          EditRoleDialog: true,
          FederatedTopologyGraph: true,
          TrainingCurveChart: true,
          ModelAggregationCard: true,
          'el-button': { template: '<button type="button"><slot /></button>' },
          'el-input': { template: '<input />' },
          'el-select': { template: '<select><slot /></select>' },
          'el-option': { template: '<option />' },
          'el-empty': { template: '<div />' },
          'el-tag': { template: '<span><slot /></span>' },
          'el-progress': true,
          'el-icon': true
        },
        directives: {
          loading: {}
        }
      }
    })

    await wrapper.get('[data-testid="resource-tab-roles"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="role-management-panel"]').exists()).toBe(true)
    expect(roleApi.getBuiltinRoles).toHaveBeenCalled()
    expect(roleApi.getCustomRoles).toHaveBeenCalled()

    await flushPromises()

    await wrapper.get('[data-testid="resource-tab-models"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="model-management-panel"]').exists()).toBe(true)
    expect(federatedModelApi.listModels).toHaveBeenCalled()
  })
})
