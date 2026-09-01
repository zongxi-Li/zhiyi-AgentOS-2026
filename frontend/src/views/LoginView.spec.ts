import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import LoginView from './LoginView.vue'

const mountLogin = () => mount(LoginView, {
  global: {
    plugins: [ElementPlus],
    stubs: { LoginAcgDemo: true }
  }
})

describe('LoginView', () => {
  it('renders the glass auth card with login and register tabs', () => {
    const wrapper = mountLogin()

    expect(wrapper.find('[data-testid="auth-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录')
    expect(wrapper.text()).toContain('注册')
  })

  it('renders a labelled primary action for the active auth mode', () => {
    const wrapper = mountLogin()

    expect(wrapper.get('[data-testid="auth-submit"]').text()).toContain('登录')
  })
})
