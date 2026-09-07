import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { agentosApi } from '@/services/api/agentos'
import { conversationApi } from '@/services/api/conversation'
import { workflowApi } from '@/services/api/workflow'

const clearMessages = vi.fn()
const bootstrap = vi.fn()

vi.mock('@/stores/chat', () => ({
  useChatStore: () => ({
    workflowBindings: {},
    clearMessages
  })
}))

vi.mock('@/stores/workflowRuns', () => ({
  useWorkflowRunsStore: () => ({ bootstrap })
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: null,
    loadCurrentUser: vi.fn(),
    setCurrentUser: vi.fn()
  })
}))

vi.mock('@/services/api/auth', () => ({
  authApi: { logout: vi.fn() }
}))

vi.mock('@/services/api/conversation', () => ({
  conversationApi: {
    getUserConversations: vi.fn().mockResolvedValue([]),
    deleteConversation: vi.fn()
  }
}))

vi.mock('@/services/api/agentos', () => ({
  agentosApi: {
    listMissions: vi.fn()
  }
}))

vi.mock('@/services/api/workflow', () => ({
  workflowApi: {
    listRuns: vi.fn()
  }
}))

const passthrough = { template: '<div><slot /></div>' }
const iconStub = { template: '<span><slot /></span>' }

const missions = [
  {
    missionId: 'mission_1', userId: 'user_1', title: '供应商质量追溯', description: '目标', status: 'created',
    latestRunId: 'run_2', latestRunStatus: 'failed', createdAt: '2026-09-05T00:00:00Z', updatedAt: '2026-09-06T00:00:00Z', runCount: 2
  },
  {
    missionId: 'mission_2', userId: 'user_1', title: '医院门诊优化', description: '流程', status: 'created',
    latestRunId: 'run_3', latestRunStatus: 'completed', createdAt: '2026-09-04T00:00:00Z', updatedAt: '2026-09-05T00:00:00Z', runCount: 3
  }
]

describe('App Agent project sidebar', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('layout.workspace_mode', 'agent')
    localStorage.setItem('layout.chat_nav_open', '1')
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    })
    vi.mocked(agentosApi.listMissions).mockResolvedValue({ items: missions, total: missions.length, page: 1, pageSize: 100 })
    vi.mocked(workflowApi.listRuns).mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 100 })
  })

  afterEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('uses one sidebar row per Mission and the canonical project count', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/chat', component: { template: '<div />' } },
        { path: '/history', component: { template: '<div />' } },
        { path: '/agentos/missions/:missionId/workspace', component: { template: '<div />' } }
      ]
    })
    await router.push('/chat?workspace=agent')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        mocks: { $t: (key: string) => key },
        stubs: {
          AppTopBar: passthrough,
          DesktopRuntimeStatus: passthrough,
          UserAvatar: passthrough,
          ErrorBoundary: passthrough,
          'el-container': passthrough,
          'el-aside': passthrough,
          'el-main': passthrough,
          'el-menu': passthrough,
          'el-menu-item': passthrough,
          'el-drawer': passthrough,
          'el-alert': passthrough,
          'el-icon': iconStub
        }
      }
    })
    await flushPromises()

    expect(agentosApi.listMissions).toHaveBeenCalledWith(
      { page: 1, pageSize: 100 },
      { signal: expect.any(AbortSignal) }
    )
    expect(workflowApi.listRuns).not.toHaveBeenCalled()
    expect(wrapper.find('.chat-project-count').text()).toBe('2')
    expect(wrapper.findAll('.chat-project-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('供应商质量追溯')
    expect(wrapper.text()).toContain('医院门诊优化')
    expect(wrapper.text()).not.toContain('ACG 历史记录')
    expect(wrapper.text()).not.toContain('联邦管理')
    expect(wrapper.text()).not.toContain('模型管理')
    expect(wrapper.text()).not.toContain('nav.roles')

    await wrapper.findAll('.chat-project-action-trigger')[0].trigger('click')
    await flushPromises()
    expect(document.body.querySelector('.sidebar-action-menu')?.textContent).toContain('归档项目')
    expect(document.body.querySelector('.sidebar-action-menu')?.textContent).toContain('删除项目')

    await wrapper.findAll('.chat-project-item')[0].trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.params.missionId).toBe('mission_1')
    expect(router.currentRoute.value.query.runId).toBe('run_2')

    wrapper.unmount()
  })

  it('routes the Agent history shortcut to the unified ACG history tab', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/chat', component: { template: '<div />' } },
        { path: '/history', component: { template: '<div />' } }
      ]
    })
    await router.push('/chat?workspace=agent')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        mocks: { $t: (key: string) => key },
        stubs: {
          AppTopBar: passthrough,
          DesktopRuntimeStatus: passthrough,
          UserAvatar: passthrough,
          ErrorBoundary: passthrough,
          'el-container': passthrough,
          'el-aside': passthrough,
          'el-main': passthrough,
          'el-menu': passthrough,
          'el-menu-item': passthrough,
          'el-drawer': passthrough,
          'el-alert': passthrough,
          'el-icon': iconStub
        }
      }
    })
    await flushPromises()

    await wrapper.find('.history-action').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/history')
    expect(router.currentRoute.value.query).toMatchObject({ tab: 'acg', source: 'agent' })

    wrapper.unmount()
  })

  it('exposes edit and delete actions for Chat conversations', async () => {
    localStorage.setItem('layout.workspace_mode', 'chat')
    vi.mocked(conversationApi.getUserConversations).mockResolvedValue([{
      id: 'conversation_1', userId: 'user_1', contextId: 'context_1', title: '项目讨论',
      workspaceMode: 'chat', createdAt: '2026-09-05T00:00:00Z', updatedAt: '2026-09-06T00:00:00Z'
    }])
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/chat', component: { template: '<div />' } },
        { path: '/history', component: { template: '<div />' } }
      ]
    })
    await router.push('/chat?workspace=chat')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        mocks: { $t: (key: string) => key },
        stubs: {
          AppTopBar: passthrough,
          DesktopRuntimeStatus: passthrough,
          UserAvatar: passthrough,
          ErrorBoundary: passthrough,
          'el-container': passthrough,
          'el-aside': passthrough,
          'el-main': passthrough,
          'el-menu': passthrough,
          'el-menu-item': passthrough,
          'el-drawer': passthrough,
          'el-alert': passthrough,
          'el-icon': iconStub
        }
      }
    })
    await flushPromises()

    expect(wrapper.findAll('.chat-project-action')).toHaveLength(3)
    expect(wrapper.find('.chat-project-action--edit').exists()).toBe(true)
    expect(wrapper.find('.chat-project-action--delete').exists()).toBe(true)
    expect(wrapper.find('.chat-project-action--open').exists()).toBe(true)

    await wrapper.find('.chat-project-row').trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    const menu = document.body.querySelector('.sidebar-action-menu')
    expect(menu?.textContent).toContain('编辑标题')
    expect(menu?.textContent).toContain('删除对话')

    wrapper.unmount()
  })
})
