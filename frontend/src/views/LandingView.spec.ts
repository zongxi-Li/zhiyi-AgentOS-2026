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

    expect(wrapper.text()).toContain('让智能体，成为复杂工作的协作者')
    expect(wrapper.findAll('.capability-card')).toHaveLength(4)
    expect(wrapper.findAll('.landing-info-card')).toHaveLength(5)
    expect(wrapper.text()).toContain('理解与规划')
    expect(wrapper.text()).toContain('连接模型、知识与智能体')
  })
})
