import { mount } from '@vue/test-utils'
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

    expect(testRouter.currentRoute.value.path).toBe('/history')
    expect(testRouter.currentRoute.value.query.tab).toBe('acg')
  })
})
