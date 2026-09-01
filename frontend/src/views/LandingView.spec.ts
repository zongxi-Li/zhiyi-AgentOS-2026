import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import LandingView from './LandingView.vue'

describe('LandingView', () => {
  it('sends visitors to login from the primary CTA', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: LandingView },
        { path: '/login', component: { template: '<div />' } }
      ]
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(LandingView, {
      global: {
        plugins: [router],
        stubs: { 'el-icon': { template: '<span><slot /></span>' } }
      }
    })

    await wrapper.get('[data-testid="landing-cta"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/login')
  })
})
