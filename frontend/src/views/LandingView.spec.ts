import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import LandingView from './LandingView.vue'

describe('LandingView', () => {
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
        stubs: { 'el-icon': { template: '<span><slot /></span>' } }
      }
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
})
