import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import LoginView from './LoginView.vue'

const mountLogin = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', component: LoginView }, { path: '/', component: { template: '<div />' } }]
  })
  await router.push('/login')
  await router.isReady()
  return mount(LoginView, {
    global: {
      plugins: [router, ElementPlus, createPinia()],
      stubs: { LoginAcgDemo: true }
    }
  })
}

describe('LoginView', () => {
  it('renders the glass auth card with login and register tabs', async () => {
    const wrapper = await mountLogin()

    expect(wrapper.find('[data-testid="auth-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录')
    expect(wrapper.text()).toContain('注册')
  })

  it('renders a labelled primary action for the active auth mode', async () => {
    const wrapper = await mountLogin()

    expect(wrapper.get('[data-testid="auth-submit"]').text()).toContain('登录')
  })
})
