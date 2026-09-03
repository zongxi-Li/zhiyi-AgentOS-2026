import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LandingView from './LandingView.vue'

const platformState = vi.hoisted(() => ({ desktop: false }))

vi.mock('@/platform', () => ({
  isDesktop: () => platformState.desktop,
  // getter：mock 工厂只在首次导入时执行一次，普通字面量会把 web 形态固化进对象。
  platform: {
    get platform() { return platformState.desktop ? 'desktop' : 'web' },
    get dragRegionProps() { return platformState.desktop ? { 'data-tauri-drag-region': '' } : {} }
  }
}))

describe('LandingView', () => {
  beforeEach(() => {
    platformState.desktop = false
  })

  const mountLanding = async ({ attach = false }: { attach?: boolean } = {}) => {
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
        stubs: { 'el-icon': { template: '<span><slot /></span>' } }
      },
      // scrollToSection 走 document.getElementById，必须真挂进 document 才找得到锚点。
      attachTo: attach ? document.body : undefined
    }) }
  }

  it('sends visitors to login from the primary CTA', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('[data-testid="landing-cta"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('presents the refined product message and capability cards', async () => {
    const { wrapper } = await mountLanding()

    expect(wrapper.text()).toContain('让智能体成为协作者')
    expect(wrapper.findAll('.capability-card')).toHaveLength(4)
    expect(wrapper.findAll('.landing-info-card')).toHaveLength(5)
    expect(wrapper.find('[data-testid="landing-scroll-hint"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('从目标，到结果')
    expect(wrapper.text()).toContain('模型、知识、工具')
    expect(wrapper.text()).not.toContain('从理解任务、动态规划到结果复核')
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

  it('scrolls to the section in place instead of letting the anchor hijack the hash router', async () => {
    // jsdom 没实现 scrollIntoView，直接挂 mock。
    const scrollMock = vi.fn()
    HTMLElement.prototype.scrollIntoView = scrollMock
    const { router, wrapper } = await mountLanding({ attach: true })
    try {
      await wrapper.findAll('.landing-nav a')[1].trigger('click')
      await flushPromises()

      expect(scrollMock).toHaveBeenCalled()
      expect(router.currentRoute.value.path).toBe('/')
    } finally {
      wrapper.unmount()
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView
    }
  })

  it('keeps the brand link a SPA navigation to the landing route', async () => {
    const { router, wrapper } = await mountLanding()

    await wrapper.get('.landing-brand').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
  })
})
