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

describe('LandingView', () => {
  beforeEach(() => {
    platformState.desktop = false
  })

  const mountLanding = async (initialPath = '/') => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: LandingView },
        { path: '/login', component: { template: '<div />' } }
      ]
    })
    await router.push(initialPath)
    await router.isReady()
    return { router, wrapper: mount(LandingView, {
      global: {
        plugins: [router, createPinia()],
        stubs: {
          'el-icon': { template: '<span><slot /></span>' },
          LoginView: { template: '<div data-testid="embedded-auth">登录注册窗口</div>' }
        }
      }
    }) }
  }

  it('routes the primary CTA to standalone login and preserves the landing return target', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('[data-testid="landing-cta"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/chat')
    expect(router.currentRoute.value.query.from).toBe('/')
  })

  it('exposes an accessible public theme toggle', async () => {
    const { wrapper } = await mountLanding()

    const toggle = wrapper.get('[data-testid="landing-theme-toggle"]')
    expect(toggle.attributes('aria-label')).toBe('切换到明亮模式')
    expect(toggle.attributes('title')).toBe('切换到明亮模式')
  })

  it('preserves the active landing section when entering login from the final CTA', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-nav a[href="#about"]').trigger('click')
    await flushPromises()
    await wrapper.get('.landing-cta--small').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.from).toBe('/#about')
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
    expect(wrapper.text()).toContain('二龙山')
    expect(wrapper.text()).toContain('游击队')
    expect(wrapper.text()).toContain('PHONE / 电话')
    expect(wrapper.text()).toContain('EMAIL / 邮箱')
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

  it('keeps the active section in the router hash for direct return navigation', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.findAll('.landing-nav a')[1].trigger('click')
    await flushPromises()

    expect(wrapper.find('a[href="#features"]').classes()).toContain('is-active')
    expect(wrapper.find('.landing-track').attributes('style')).toContain('translate3d(0px, -25%, 0px)')
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.hash).toBe('#features')
  })

  it('opens directly on the section encoded in the landing hash', async () => {
    const { router, wrapper } = await mountLanding('/#ecosystem')

    expect(router.currentRoute.value.hash).toBe('#ecosystem')
    expect(wrapper.find('a[href="#ecosystem"]').classes()).toContain('is-active')
    expect(wrapper.find('.landing-track').attributes('style')).toContain('translate3d(0px, -50%, 0px)')
  })

  it('keeps the brand link a SPA navigation to the landing route', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-brand').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
  })
})
