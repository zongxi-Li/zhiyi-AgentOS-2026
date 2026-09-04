import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
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

describe('LandingView', () => {
  beforeEach(() => {
    platformState.desktop = false
  })

  const mountLanding = async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: LandingView },
        { path: '/login', component: { template: '<div />' } }
      ]
    })
    await router.push('/')
    await router.isReady()
    return { router, wrapper: mount(LandingView, {
      global: {
        plugins: [router],
        stubs: {
          'el-icon': { template: '<span><slot /></span>' },
          LoginView: { template: '<div data-testid="embedded-auth">登录注册窗口</div>' }
        }
      }
    }) }
  }

  it('replaces the landing surface with auth from the primary CTA without routing away', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('[data-testid="landing-cta"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="landing-page-home"]').exists()).toBe(false)
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('replaces the landing surface with auth from the final enter CTA', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-nav a[href="#about"]').trigger('click')
    await wrapper.get('.landing-cta--small').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="embedded-auth"]').exists()).toBe(true)
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('presents a focused light landing sequence without legacy floating chrome', async () => {
    const { wrapper } = await mountLanding()

    expect(wrapper.text()).toContain('让智能体成为协作者')
    expect(wrapper.findAll('.capability-card')).toHaveLength(0)
    expect(wrapper.findAll('.landing-orbit-label')).toHaveLength(0)
    expect(wrapper.find('[data-testid="landing-scroll-hint"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid^="landing-page-"]')).toHaveLength(4)
    expect(wrapper.findAll('.landing-info-card')).toHaveLength(5)
    expect(wrapper.text()).toContain('从目标，到结果')
    expect(wrapper.text()).toContain('统一管理模型与工具')
  })

  it('moves exactly one content page for each meaningful wheel gesture', async () => {
    const { wrapper } = await mountLanding()

    expect(wrapper.find('a[href="#home"]').classes()).toContain('is-active')

    await wrapper.trigger('wheel', { deltaY: 120 })
    expect(wrapper.find('a[href="#features"]').classes()).toContain('is-active')
    expect(wrapper.find('.landing-track').attributes('style')).toContain('translate3d(0px, -25%, 0px)')

    await wrapper.trigger('wheel', { deltaY: 120 })
    expect(wrapper.find('a[href="#features"]').classes()).toContain('is-active')
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

  it('changes pages from navigation without hijacking the router hash', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.findAll('.landing-nav a')[1].trigger('click')
    await flushPromises()

    expect(wrapper.find('a[href="#features"]').classes()).toContain('is-active')
    expect(wrapper.find('.landing-track').attributes('style')).toContain('translate3d(0px, -25%, 0px)')
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('keeps the brand link a SPA navigation to the landing route', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-brand').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
  })
})
