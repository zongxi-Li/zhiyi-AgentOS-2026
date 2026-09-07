import { mount, flushPromises } from '@vue/test-utils'
import { createWebHistory, createRouter, type Router } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import AppTopBar from './AppTopBar.vue'

const routes = [
  { path: '/', component: { template: '<div />' } },
  { path: '/agentos/acg', component: { template: '<div />' } },
  { path: '/agentos-console', component: { template: '<div />' } }
]

const mountTopBar = async (props: Record<string, unknown> = {}): Promise<{ wrapper: ReturnType<typeof mount>; router: Router }> => {
  // 用 web history：memory history 不向 state 写 position，组件的
  // 上一步/下一步禁用态在真实浏览器里靠 history.state.position 对账。
  const router = createRouter({
    history: createWebHistory(),
    routes
  })
  await router.push('/')
  await router.isReady()

  const wrapper = mount(AppTopBar, {
    props: {
      ...props
    },
    global: {
      plugins: [router],
      stubs: {
        'el-icon': { template: '<span><slot /></span>' }
      }
    }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('AppTopBar', () => {
  it('renders the shell context and command center', async () => {
    const { wrapper } = await mountTopBar()

    expect(wrapper.find('[aria-label="应用工作栏"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('知弈工作台')
    expect(wrapper.get('input').attributes('placeholder')).toBe('搜索任务、步骤、运行或命令')
  })

  it('emits shell actions and clears the command on Escape', async () => {
    const { wrapper } = await mountTopBar()

    await wrapper.get('[aria-label="收起导航"]').trigger('click')
    await wrapper.find('.app-topbar__menu-links button').trigger('click')
    await wrapper.get('input').setValue('trace')
    await wrapper.get('input').trigger('keydown.esc')

    expect(wrapper.emitted('menu')).toHaveLength(1)
    expect(wrapper.emitted('navigate')).toEqual([['/agentos/acg']])
    expect(wrapper.get('input').element).toHaveProperty('value', '')
  })

  it('uses the logo as the single navigation toggle', async () => {
    const { wrapper } = await mountTopBar({ navigationState: 'collapsed' })

    expect(wrapper.find('.app-topbar__menu-button').exists()).toBe(false)
    expect(wrapper.get('[aria-label="展开导航"]').classes()).toContain('is-collapsed')
    expect(wrapper.find('.app-topbar__logo-control').exists()).toBe(false)

    await wrapper.get('[aria-label="展开导航"]').trigger('click')
    expect(wrapper.emitted('menu')).toHaveLength(1)
  })

  it('removes the requested topbar action group', async () => {
    const { wrapper } = await mountTopBar()

    expect(wrapper.find('.app-topbar__actions').exists()).toBe(false)
    expect(wrapper.find('[aria-label="切换布局"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="打开设置"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="打开用户中心"]').exists()).toBe(false)
  })

  it('keeps the web shell free of desktop window chrome', async () => {
    const { wrapper } = await mountTopBar()

    expect(wrapper.find('.desktop-window-controls').exists()).toBe(false)
    expect(wrapper.find('[aria-label="关闭"]').exists()).toBe(false)
    expect(wrapper.find('[data-tauri-drag-region]').exists()).toBe(false)
  })

  it('starts with both history buttons disabled', async () => {
    const { wrapper } = await mountTopBar()

    expect(wrapper.get('[aria-label="上一步"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="下一步"]').attributes('disabled')).toBeDefined()
  })

  // jsdom 不派发 popstate：先把 location/state 改写回目标项，再手动派发事件
  // （vue-router 的 popstate 处理器从 window.location 读目标路由）。
  const popHistoryTo = async (state: object, path: string) => {
    window.history.replaceState(state, '', path)
    window.dispatchEvent(new PopStateEvent('popstate', { state }))
    await flushPromises()
  }

  it('delegates the history buttons to the router', async () => {
    const rootState = JSON.parse(JSON.stringify(window.history.state))
    const { wrapper, router } = await mountTopBar()
    const back = wrapper.get('[aria-label="上一步"]')
    const forward = wrapper.get('[aria-label="下一步"]')
    const backSpy = vi.spyOn(router, 'back').mockImplementation(() => {})
    const forwardSpy = vi.spyOn(router, 'forward').mockImplementation(() => {})

    await router.push('/agentos/acg')
    await flushPromises()
    expect(back.attributes('disabled')).toBeUndefined()

    await back.trigger('click')
    expect(backSpy).toHaveBeenCalledTimes(1)

    await popHistoryTo(rootState, '/')
    expect(forward.attributes('disabled')).toBeUndefined()
    await forward.trigger('click')
    expect(forwardSpy).toHaveBeenCalledTimes(1)
  })

  it('tracks the history position to toggle the buttons', async () => {
    const rootState = JSON.parse(JSON.stringify(window.history.state))
    const { wrapper, router } = await mountTopBar()
    const back = wrapper.get('[aria-label="上一步"]')
    const forward = wrapper.get('[aria-label="下一步"]')

    expect(back.attributes('disabled')).toBeDefined()
    expect(forward.attributes('disabled')).toBeDefined()

    await router.push('/agentos/acg')
    await flushPromises()
    expect(back.attributes('disabled')).toBeUndefined()
    expect(forward.attributes('disabled')).toBeDefined()

    await router.push('/agentos-console')
    await flushPromises()
    await popHistoryTo(rootState, '/')
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(back.attributes('disabled')).toBeDefined()
    expect(forward.attributes('disabled')).toBeUndefined()
  })
})
