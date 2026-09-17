import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import LoginView from './LoginView.vue'

const authApiMock = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn()
}))

vi.mock('@/services/api/auth', () => ({ authApi: authApiMock }))

const mountLogin = async (path = '/login', props: { embedded?: boolean } = {}) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', component: LoginView }, { path: '/', component: { template: '<div />' } }]
  })
  await router.push(path)
  await router.isReady()
  return { router, wrapper: mount(LoginView, {
    props,
    global: {
      plugins: [router, ElementPlus, createPinia()],
      stubs: { LoginAcgDemo: true }
    }
  }) }
}

describe('LoginView', () => {
  it('renders the glass auth card with login and register tabs', async () => {
    const { wrapper } = await mountLogin()

    expect(wrapper.find('[data-testid="auth-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录')
    expect(wrapper.text()).toContain('注册')
    expect(wrapper.find('.auth-card__eyebrow').text()).toContain('WORKSPACE ACCESS')
    expect(wrapper.get('#auth-card-title').text()).toContain('登录知弈 AgentOS')
  })

  it('exposes an accessible theme toggle in the auth topbar', async () => {
    const { wrapper } = await mountLogin()

    const toggle = wrapper.get('[data-testid="auth-theme-toggle"]')
    expect(toggle.attributes('aria-label')).toBe('切换到明亮模式')
    expect(toggle.attributes('title')).toBe('切换到明亮模式')
  })

  it('renders a labelled primary action for the active auth mode', async () => {
    const { wrapper } = await mountLogin()

    expect(wrapper.get('[data-testid="auth-submit"]').text()).toContain('登录')

    await wrapper.findAll('.el-tabs__item')[1].trigger('click')

    expect(wrapper.get('#auth-card-title').text()).toContain('创建知弈 AgentOS 账号')
    expect(wrapper.get('.auth-card__eyebrow').text()).toContain('NEW WORKSPACE')
    expect(wrapper.findAll('[data-testid="auth-submit"]').some(button => button.text().includes('立即注册'))).toBe(true)
  })

  it('keeps only the auth dialog when embedded in the landing surface', async () => {
    const { wrapper } = await mountLogin('/login', { embedded: true })

    expect(wrapper.find('.auth-topbar').exists()).toBe(false)
    expect(wrapper.find('.auth-intro').exists()).toBe(false)
    expect(wrapper.find('.auth-footer').exists()).toBe(false)
    expect(wrapper.get('.auth-card__heading').text()).toContain('继续进入你的智能协作工作空间')

    await wrapper.get('[data-testid="auth-dialog-close"]').trigger('click')

    expect(wrapper.emitted('back')).toHaveLength(1)
  })

  it('shows an inline message for rejected login credentials', async () => {
    authApiMock.login.mockRejectedValueOnce({ response: { status: 401 } })
    const { wrapper } = await mountLogin()

    await wrapper.find('input[autocomplete="username"]').setValue('demo')
    await wrapper.find('input[autocomplete="current-password"]').setValue('wrong-password')
    await wrapper.get('[data-testid="auth-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.auth-form__error').text()).toContain('账号或密码不正确')
  })

  it('returns to the landing section that opened the login page', async () => {
    const { router, wrapper } = await mountLogin('/login?from=%2F%23ecosystem')

    expect(wrapper.get('.auth-brand').exists()).toBe(true)
    await wrapper.get('.auth-brand').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.hash).toBe('#ecosystem')
  })
})
