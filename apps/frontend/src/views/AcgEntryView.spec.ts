import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { workflowApi } from '@/services/api/workflow'
import AcgEntryView from './AcgEntryView.vue'

const projectListStub = { template: '<div class="project-list-entry">projects</div>' }

const createTestRouter = async (url: string) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/agentos/acg', component: AcgEntryView },
      { path: '/agentos/missions/:missionId/workspace', name: 'MissionWorkspace', component: { template: '<div />' } }
    ]
  })
  await router.push(url)
  await router.isReady()
  return router
}

describe('AcgEntryView', () => {
  afterEach(() => vi.restoreAllMocks())

  it('redirects a legacy run entry to its Mission Workspace', async () => {
    vi.spyOn(workflowApi, 'getRun').mockResolvedValue({
      runId: 'run_1', missionId: 'mission_1'
    } as any)
    const router = await createTestRouter('/agentos/acg?runId=run_1')
    mount(AcgEntryView, {
      global: { plugins: [router], stubs: { ProjectListView: projectListStub } }
    })

    await flushPromises()

    expect(workflowApi.getRun).toHaveBeenCalledWith('run_1', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(router.currentRoute.value.name).toBe('MissionWorkspace')
    expect(router.currentRoute.value.params.missionId).toBe('mission_1')
    expect(router.currentRoute.value.query.runId).toBe('run_1')
  })

  it('opens the canonical Project list without a Run query', async () => {
    const router = await createTestRouter('/agentos/acg')
    const wrapper = mount(AcgEntryView, {
      global: { plugins: [router], stubs: { ProjectListView: projectListStub } }
    })

    await flushPromises()

    expect(wrapper.find('.project-list-entry').text()).toBe('projects')
  })
})
