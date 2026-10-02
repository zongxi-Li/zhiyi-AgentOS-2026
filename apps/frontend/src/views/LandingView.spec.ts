import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LandingView from './LandingView.vue'

const platformState = vi.hoisted(() => ({ desktop: false }))

vi.mock('@/platform', () => ({
  isDesktop: () => platformState.desktop,
  apiUrl: (path: string) => path,
  platform: {
    get platform() { return platformState.desktop ? 'desktop' : 'web' },
    get dragRegionProps() { return platformState.desktop ? { 'data-tauri-drag-region': '' } : {} }
  }
}))

vi.mock('@/views/LoginView.vue', () => ({
  default: {
    name: 'LoginView',
    template: '<div data-testid="embedded-auth">登录注册窗口</div>'
  }
}))

vi.mock('@/components/landing/GlassConstellation.vue', () => ({
  default: {
    name: 'GlassConstellation',
    template: '<div data-testid="glass-constellation">动画组件</div>'
  }
}))

describe('LandingView', () => {
  beforeEach(() => {
    platformState.desktop = false
  })

  const mountLanding = async (initialPath = '/') => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: LandingView }
      ]
    })
    await router.push(initialPath)
    await router.isReady()
    const wrapper = mount(LandingView, {
      attachTo: document.body,
      global: {
        plugins: [router, createPinia()],
        stubs: {
          'el-icon': { template: '<span><slot /></span>' }
        }
      }
    })
    await vi.dynamicImportSettled()
    await flushPromises()
    return { router, wrapper }
  }

  it('switches the hero visual slot to embedded auth from the primary CTA', async () => {
    const { router, wrapper } = await mountLanding()

    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(false)

    await wrapper.get('[data-testid="landing-cta"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(false)
  })

  it('exposes an accessible public theme toggle', async () => {
    const { wrapper } = await mountLanding()

    const toggle = wrapper.get('[data-testid="landing-theme-toggle"]')
    expect(toggle.attributes('aria-label')).toBe('切换到明亮模式')
    expect(toggle.attributes('title')).toBe('切换到明亮模式')
  })

  it('lets the visitor switch the overall landing style and persists it', async () => {
    localStorage.removeItem('kinlin:landing-style')
    const { wrapper } = await mountLanding()

    expect(wrapper.find('.landing-view').classes()).not.toContain('is-style-star')
    expect(document.documentElement.dataset.landingStyle).toBe('paper')

    await wrapper.get('[data-testid="landing-style-toggle"]').trigger('click')
    const options = wrapper.findAll('.landing-style-picker__option')
    expect(options).toHaveLength(2)
    await options[1].trigger('click')
    await flushPromises()

    expect(wrapper.find('.landing-view').classes()).toContain('is-style-star')
    expect(localStorage.getItem('kinlin:landing-style')).toBe('star')
    expect(document.documentElement.dataset.landingStyle).toBe('star')
    wrapper.unmount()
  })

  it('returns to the hero and opens embedded auth from the final CTA', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-nav a[href="#about"]').trigger('click')
    await flushPromises()
    await wrapper.get('.landing-cta--small').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.query.auth).toBe('1')
    expect(wrapper.find('a[href="#home"]').classes()).toContain('is-active')
    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(true)
  })

  it('opens embedded auth when requested by the landing query', async () => {
    const { wrapper } = await mountLanding('/?auth=1&redirect=/chat')

    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(false)
  })

  it('presents the long-horizon scrolling landing with dense real product content', async () => {
    const { wrapper } = await mountLanding()

    expect(wrapper.text()).toContain('把超长程复杂任务，做成可交付的闭环')
    expect(wrapper.find('.landing-header__login').exists()).toBe(false)
    expect(wrapper.findAll('.capability-card')).toHaveLength(0)
    expect(wrapper.findAll('.landing-orbit-label')).toHaveLength(0)
    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid^="landing-page-"]')).toHaveLength(6)
    expect(wrapper.find('[data-testid="mission-run-demo"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="landing-capability-strip"]').exists()).toBe(true)
    expect(wrapper.findAll('.landing-info-card')).toHaveLength(19)
    expect(wrapper.text()).toContain('Agentic Computation Graph')
    expect(wrapper.text()).toContain('Checkpoint CAS')
    expect(wrapper.text()).toContain('GraphPatch')
    expect(wrapper.text()).toContain('记忆不坍缩')
    expect(wrapper.text()).toContain('低熵通信')
    expect(wrapper.text()).toContain('Provenance')
    expect(wrapper.text()).toContain('法律 · 黄金纵切')
    expect(wrapper.text()).toContain('General-Native')
    expect(wrapper.text()).toContain('自定义任务')
    expect(wrapper.text()).toContain('从目标，到结果')
    expect(wrapper.text()).toContain('统一管理模型与工具')
    expect(wrapper.text()).toContain('二龙山')
    expect(wrapper.text()).toContain('游击队')
    expect(wrapper.text()).toContain('PHONE / 电话')
    expect(wrapper.text()).toContain('EMAIL / 邮箱')
    wrapper.unmount()
  })

  it('routes each capability strip entry to its real module through embedded auth', async () => {
    const { router, wrapper } = await mountLanding()

    const strip = wrapper.get('[data-testid="landing-capability-strip"]')
    expect(strip.findAll('.landing-capability-strip__item')).toHaveLength(6)

    await strip.findAll('.landing-capability-strip__item')[4].trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.auth).toBe('1')
    expect(router.currentRoute.value.query.redirect).toBe('/agentos/resources')
    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(true)
  })

  it('marks the clicked nav section active and keeps it in the router hash', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.findAll('.landing-nav a')[2].trigger('click')
    await flushPromises()

    expect(wrapper.find('a[href="#horizon"]').classes()).toContain('is-active')
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.hash).toBe('#horizon')
    wrapper.unmount()
  })

  it('keeps the page web-only in the browser shell: no desktop chrome class or drag region', async () => {
    const { wrapper } = await mountLanding()

    expect(wrapper.find('.landing-view').classes()).not.toContain('is-desktop-shell')
    expect(wrapper.find('.landing-header').attributes('data-tauri-drag-region')).toBeUndefined()
  })

  it('mounts the window drag region on the header when running in the desktop shell', async () => {
    platformState.desktop = true
    const { wrapper } = await mountLanding()

    expect(wrapper.find('.landing-view').classes()).toContain('is-desktop-shell')
    expect(wrapper.find('.landing-header').attributes('data-tauri-drag-region')).toBe('')
  })

  it('keeps the brand link a SPA navigation to the landing route', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-brand').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
  })
})
