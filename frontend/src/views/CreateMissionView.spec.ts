import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { workflowApi } from '@/services/api/workflow'
import CreateMissionView from './CreateMissionView.vue'

vi.mock('@/services/api/workflow', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/api/workflow')>()
  return {
    ...actual,
    workflowApi: {
      ...actual.workflowApi,
      createMaterial: vi.fn(),
      startWorkflowAsync: vi.fn()
    }
  }
})

const workbenchLayoutStub = {
  template: '<section class="workbench-layout-stub"><slot name="main" /></section>'
}

describe('CreateMissionView', () => {
  afterEach(() => vi.restoreAllMocks())

  it('creates a Mission and hands the accepted Run to Workspace', async () => {
    vi.mocked(workflowApi.startWorkflowAsync).mockResolvedValue({
      missionId: 'mission_new',
      runId: 'run_new',
      status: 'pending'
    } as any)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/agentos/missions/new', name: 'CreateMission', component: CreateMissionView },
        { path: '/agentos/acg', name: 'AcgVisualization', component: { template: '<div />' } },
        { path: '/agentos/missions/:missionId/workspace', name: 'MissionWorkspace', component: { template: '<div />' } }
      ]
    })
    await router.push({ name: 'CreateMission' })
    await router.isReady()
    const wrapper = mount(CreateMissionView, {
      global: {
        plugins: [router],
        stubs: { WorkbenchLayout: workbenchLayoutStub, 'el-icon': true }
      }
    })

    await wrapper.find('#mission-title').setValue('新建工程')
    await wrapper.find('#mission-goal').setValue('输出可验收的实施方案')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledWith(
      expect.objectContaining({ title: '新建工程', input: expect.objectContaining({ taskGoal: '输出可验收的实施方案' }) }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(router.currentRoute.value.name).toBe('MissionWorkspace')
    expect(router.currentRoute.value.params.missionId).toBe('mission_new')
    expect(router.currentRoute.value.query.runId).toBe('run_new')
    expect(wrapper.text()).not.toContain('ACG Dashboard')
    wrapper.unmount()
  })

  it('keeps the create page separate from the Project list', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/agentos/missions/new', name: 'CreateMission', component: CreateMissionView },
        { path: '/agentos/acg', name: 'AcgVisualization', component: { template: '<div />' } }
      ]
    })
    await router.push({ name: 'CreateMission' })
    await router.isReady()
    const wrapper = mount(CreateMissionView, {
      global: {
        plugins: [router],
        stubs: { WorkbenchLayout: workbenchLayoutStub, 'el-icon': true }
      }
    })

    expect(wrapper.find('[aria-label="Create Mission"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Runtime Configuration')
    expect(wrapper.text()).not.toContain('工程项目')
    wrapper.unmount()
  })
})
