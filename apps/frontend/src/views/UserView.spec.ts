import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import request from '@/utils/request'
import { useUserStore } from '@/stores/user'
import { userApi } from '@/services/api/user'
import UserView from './UserView.vue'

vi.mock('@/utils/request', () => ({ default: { get: vi.fn() } }))
vi.mock('@/stores/chat', () => ({ useChatStore: () => ({ messages: [] }) }))
vi.mock('@/stores/workflowRuns', () => ({ useWorkflowRunsStore: () => ({ references: {} }) }))
vi.mock('@/services/api/user', () => ({ userApi: { getAvatar: vi.fn() } }))
vi.mock('@/services/api/conversation', () => ({ conversationApi: { getUserConversations: vi.fn().mockResolvedValue([]) } }))
vi.mock('@/services/api/workflow', () => ({ workflowApi: { listRuns: vi.fn().mockResolvedValue({ items: [] }) } }))

describe('saved profile display', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks() })

  it('refreshes a recently seeded login profile and displays its saved avatar and metadata', async () => {
    const pinia = createPinia()
    const store = useUserStore(pinia)
    store.setCurrentUser({ id: 'local-user', username: 'lzx', email: 'lzx@localhost.local' })
    vi.mocked(request.get).mockResolvedValue({ data: {
      id: 'local-user', username: 'lzx', email: null,
      avatar: 'avatars/local-user/saved.png', createdAt: '2026-11-24T08:00:00Z'
    } })
    vi.mocked(userApi.getAvatar).mockResolvedValue(new Blob(['image'], { type: 'image/png' }))
    const createObjectURL = vi.fn().mockReturnValue('blob:saved-avatar')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL, revokeObjectURL }))
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: UserView }] })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(UserView, { global: { plugins: [pinia, router], stubs: {
      ElIcon: true, ElForm: { template: '<form><slot /></form>' },
      ElFormItem: { template: '<div><slot /></div>' }, ElInput: true, ElButton: true
    } } })
    await flushPromises()
    expect(request.get).toHaveBeenCalledWith('/user/profile', { timeout: 10000 })
    expect(userApi.getAvatar).toHaveBeenCalledWith('local-user')
    expect(wrapper.get('.hero-avatar img').attributes('src')).toBe('blob:saved-avatar')
    expect(wrapper.get('.hero-handle').text()).toContain('未设置邮箱')
    expect(wrapper.text()).not.toContain('localhost.local')
    expect(wrapper.get('.insight-list').text()).toContain('2026年11月24日')
    wrapper.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:saved-avatar')
  })
})
