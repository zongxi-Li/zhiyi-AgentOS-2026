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
      uploadAttachment: vi.fn(),
      deleteAttachment: vi.fn(),
      startWorkflowAsync: vi.fn()
    }
  }
})

const workbenchLayoutStub = {
  template: '<section class="workbench-layout-stub"><slot name="main" /></section>'
}

describe('CreateMissionView', () => {
  afterEach(() => vi.resetAllMocks())

  it('renders the mission launcher arrangement and restores runtime settings', async () => {
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
        stubs: { WorkbenchLayout: workbenchLayoutStub, PluginExtensionHost: true }
      }
    })

    expect(wrapper.find('#mission-title').exists()).toBe(false)
    expect(wrapper.find('#mission-files').exists()).toBe(true)
    expect(wrapper.find('#mission-goal').exists()).toBe(true)
    expect(wrapper.text()).toContain('Execution')
    expect(wrapper.text()).toContain('Advanced Runtime Settings')
    expect(wrapper.find('.create-mission__submit').text()).toContain('创建并运行')
    expect(wrapper.find('.create-mission__back').text()).toContain('返回项目')
    expect(wrapper.find('.create-mission__workspace').exists()).toBe(true)
    expect(wrapper.find('.launch-bar').exists()).toBe(true)
    wrapper.unmount()
  })

  it('derives a launch summary and keeps Create & Run disabled until the brief is ready', async () => {
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
        stubs: { WorkbenchLayout: workbenchLayoutStub, PluginExtensionHost: true }
      }
    })

    expect(wrapper.find('.context-empty').exists()).toBe(true)
    expect(wrapper.find('.execution-settings').exists()).toBe(true)
    expect(wrapper.findAll('.execution-settings .config-option').length).toBeGreaterThan(0)
    expect(wrapper.find('.create-mission__submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.launch-bar__summary').text()).toContain('Dynamic · Native Core')

    await wrapper.find('#mission-goal').setValue('验证 Mission brief 可以启动 Run')
    expect(wrapper.find('.create-mission__submit').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('returns to the project list without retaining the create route', async () => {
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
        stubs: { WorkbenchLayout: workbenchLayoutStub, PluginExtensionHost: true }
      }
    })

    await wrapper.find('.create-mission__back').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('AcgVisualization')
    expect(router.currentRoute.value.query).toEqual({})
    wrapper.unmount()
  })

  it('renders GLM reasoning_effort choices and excludes disabled thinking', async () => {
    localStorage.setItem('kinlin.model_settings', JSON.stringify({
      provider: 'glm',
      apiKey: '',
      baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
      models: ['glm-5.3-flash'],
      selectedModel: 'glm-5.3-flash',
      thinkingMode: 'deep',
      reasoningEffort: 'high'
    }))
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
        stubs: { WorkbenchLayout: workbenchLayoutStub, PluginExtensionHost: true }
      }
    })

    const select = wrapper.find('select[aria-label="Thinking strength"]')
    expect(select.findAll('option').map(option => option.attributes('value'))).toEqual(['low', 'high', 'max'])
    expect((select.element as HTMLSelectElement).value).toBe('high')
    await select.setValue('low')
    expect((select.element as HTMLSelectElement).value).toBe('low')

    wrapper.unmount()
    localStorage.removeItem('kinlin.model_settings')
  })

  it('starts a Run with the configured Mission and hands it to Workspace', async () => {
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
        stubs: { WorkbenchLayout: workbenchLayoutStub, PluginExtensionHost: true }
      }
    })

    await wrapper.find('#mission-goal').setValue('输出可验收的实施方案')
    await wrapper.findAll('.config-option').find(button => button.text().includes('Template preferred'))?.trigger('click')
    await wrapper.find('select[aria-label="Planning diversity"]').setValue('exploratory')
    await wrapper.find('input[type="number"]').setValue('42')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '输出可验收的实施方案',
        input: expect.objectContaining({
          taskGoal: '输出可验收的实施方案',
          planningMode: 'template_preferred',
          planningDiversity: 'exploratory',
          planningSeed: 42,
          usePlanner: true,
          debugTrace: false,
          lowEntropyOptions: ['trace_provenance']
        })
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    expect(router.currentRoute.value.name).toBe('MissionWorkspace')
    expect(router.currentRoute.value.params.missionId).toBe('mission_new')
    expect(router.currentRoute.value.query.runId).toBe('run_new')
    wrapper.unmount()
  })

  it('uploads files first and submits only READY attachment identities', async () => {
    vi.mocked(workflowApi.uploadAttachment).mockResolvedValue({
        attachmentId: 'att_contract', originalFilename: 'contract.txt', filename: 'contract.txt',
        mimeType: 'text/plain', extension: '.txt', sizeBytes: 18, sha256: 'a'.repeat(64),
        status: 'READY', characterCount: 18, parser: 'plain-text:utf-8-sig', metadata: {},
        createdAt: '2026-09-12T00:00:00Z', updatedAt: '2026-09-12T00:00:00Z'
    })
    vi.mocked(workflowApi.startWorkflowAsync).mockResolvedValue({
      missionId: 'mission_attachment', runId: 'run_attachment', status: 'pending'
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
      global: { plugins: [router], stubs: { WorkbenchLayout: workbenchLayoutStub, PluginExtensionHost: true } }
    })
    const file = new File(['amount is 800000'], 'contract.txt', { type: 'text/plain' })
    const input = wrapper.find('#mission-files')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await vi.waitFor(() => expect(workflowApi.uploadAttachment).toHaveBeenCalledWith(file, expect.any(Object)))
    await flushPromises()
    expect(wrapper.text()).toContain('TXT · 16 B')
    expect(wrapper.text()).toContain('✓ 已就绪')
    await wrapper.find('#mission-goal').setValue('生成最终合同审查报告')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(workflowApi.startWorkflowAsync).toHaveBeenCalledWith(
      expect.objectContaining({ attachmentIds: ['att_contract'] }),
      expect.any(Object)
    )
    expect(workflowApi.deleteAttachment).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
