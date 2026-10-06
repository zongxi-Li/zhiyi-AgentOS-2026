import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import HistoryView from './HistoryView.vue'

describe('HistoryView tabs', () => {
  it('includes ACG history and synchronizes its tab to the URL', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/history', component: HistoryView }]
    })
    await testRouter.push('/history')
    await testRouter.isReady()

    const wrapper = mount(HistoryView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          ConversationList: { template: '<div />' },
          FileHistoryList: { template: '<div />' },
          AcgHistoryPanel: { template: '<div data-testid="acg-history-panel-stub" />' },
          'el-icon': true
        }
      }
    })

    expect(wrapper.text()).toContain('对话历史')
    expect(wrapper.text()).toContain('文件历史')
    expect(wrapper.text()).toContain('ACG 历史')
    await wrapper.get('[data-testid="history-tab-acg"]').trigger('click')
    await flushPromises()

    expect(testRouter.currentRoute.value.path).toBe('/history')
    expect(testRouter.currentRoute.value.query.tab).toBe('acg')
  })

  it('defaults to conversations and follows browser query changes', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/history', component: HistoryView }]
    })
    await testRouter.push('/history')
    await testRouter.isReady()

    const wrapper = mount(HistoryView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          ConversationList: { template: '<div data-testid="conversation-history" />' },
          FileHistoryList: { template: '<div data-testid="file-history" />' },
          AcgHistoryPanel: { template: '<div data-testid="acg-history" />' },
          'el-icon': true
        }
      }
    })

    expect(wrapper.get('[data-testid="history-tab-conversations"]').classes()).toContain('active')
    expect(wrapper.find('[data-testid="conversation-history"]').exists()).toBe(true)

    await testRouter.push('/history?tab=files')
    await flushPromises()

    expect(wrapper.get('[data-testid="history-tab-files"]').classes()).toContain('active')
    expect(wrapper.find('[data-testid="file-history"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="conversation-history"]').exists()).toBe(false)
  })

  it('follows browser back and forward tab changes', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/history', component: HistoryView }]
    })
    await testRouter.push('/history')
    await testRouter.isReady()

    const wrapper = mount(HistoryView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          ConversationList: { template: '<div data-testid="conversation-history" />' },
          FileHistoryList: { template: '<div data-testid="file-history" />' },
          AcgHistoryPanel: { template: '<div data-testid="acg-history" />' },
          'el-icon': true
        }
      }
    })

    await testRouter.push('/history?tab=files')
    await testRouter.push('/history?tab=acg')
    await flushPromises()
    expect(wrapper.get('[data-testid="history-tab-acg"]').classes()).toContain('active')

    testRouter.back()
    await flushPromises()
    expect(wrapper.get('[data-testid="history-tab-files"]').classes()).toContain('active')

    testRouter.forward()
    await flushPromises()
    expect(wrapper.get('[data-testid="history-tab-acg"]').classes()).toContain('active')
  })

  it('normalizes an unknown tab query to the default URL', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/history', component: HistoryView }]
    })
    await testRouter.push('/history?tab=unknown')
    await testRouter.isReady()

    mount(HistoryView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          ConversationList: { template: '<div />' },
          FileHistoryList: { template: '<div />' },
          AcgHistoryPanel: { template: '<div />' },
          'el-icon': true
        }
      }
    })
    await flushPromises()

    expect(testRouter.currentRoute.value.fullPath).toBe('/history')
  })

  it('renders the projects-style header with a toolbar row below the title', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/history', component: HistoryView }]
    })
    await testRouter.push('/history')
    await testRouter.isReady()

    const wrapper = mount(HistoryView, {
      global: {
        plugins: [testRouter, createPinia()],
        stubs: {
          ConversationList: { template: '<div />' },
          FileHistoryList: { template: '<div />' },
          AcgHistoryPanel: { template: '<div />' },
          'el-icon': true
        }
      }
    })

    expect(wrapper.get('.history-header h1').text()).toBe('历史记录')
    expect(wrapper.get('.history-toolbar .history-search input').attributes('placeholder')).toBe('搜索历史记录...')
    expect(wrapper.find('[data-testid="history-tab-conversations"]').exists()).toBe(true)
  })
})
