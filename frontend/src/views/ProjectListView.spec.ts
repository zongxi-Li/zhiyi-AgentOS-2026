import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import { ElMessageBox } from 'element-plus'
import ProjectListView from './ProjectListView.vue'

const layoutStub = {
  template: '<main class="layout-stub"><slot name="main" /></main>'
}

const missions = [
  {
    missionId: 'mission_1', userId: 'user_1', title: '设备人员规划', description: '目标', status: 'created',
    latestRunId: 'run_1', latestRunStatus: 'completed', createdAt: '2026-08-28T00:00:00Z', updatedAt: '2026-08-28T01:00:00Z', runCount: 1
  },
  {
    missionId: 'mission_2', userId: 'user_1', title: '医院门诊优化', description: '流程', status: 'created',
    latestRunId: 'run_2', latestRunStatus: 'running', createdAt: '2026-08-28T00:00:00Z', updatedAt: '2026-08-28T02:00:00Z', runCount: 2
  }
]

const mountedWrappers: Array<{ unmount: () => void }> = []

const mountPage = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/agentos/acg', name: 'AcgVisualization', component: { template: '<div />' } },
      { path: '/agentos/missions/new', name: 'CreateMission', component: { template: '<div />' } },
      { path: '/agentos/missions/:missionId/workspace', name: 'MissionWorkspace', component: { template: '<div />' } }
    ]
  })
  await router.push('/agentos/acg')
  await router.isReady()
  vi.spyOn(agentosApi, 'listMissions').mockResolvedValue({ items: missions, total: missions.length, page: 1, pageSize: 100 })
  const wrapper = mount(ProjectListView, {
    global: { plugins: [router], stubs: { WorkbenchLayout: layoutStub, 'el-icon': true } }
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}

describe('ProjectListView', () => {
  afterEach(() => {
    mountedWrappers.splice(0).forEach(wrapper => wrapper.unmount())
    document.body.querySelector('#project-action-menu')?.remove()
    localStorage.removeItem('zhiyi.projects.view-mode.v1')
    vi.restoreAllMocks()
  })

  it('renders one row per Mission instead of one row per Run', async () => {
    const { wrapper } = await mountPage()
    expect(agentosApi.listMissions).toHaveBeenCalledWith({ page: 1, pageSize: 100 }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findAll('.project-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('1 Runs')
    expect(wrapper.text()).toContain('2 Runs')
  })

  it('filters Project rows by title or Mission ID', async () => {
    const { wrapper } = await mountPage()
    await wrapper.find('input[type="search"]').setValue('mission_2')
    expect(wrapper.findAll('.project-row')).toHaveLength(1)
    expect(wrapper.find('.project-row').text()).toContain('医院门诊优化')
  })

  it('switches between the reference list view and a card grid and remembers the choice', async () => {
    const { wrapper } = await mountPage()

    expect(wrapper.find('.project-list__rows').classes()).not.toContain('is-grid')
    expect(wrapper.find('[data-view-mode="list"]').attributes('aria-pressed')).toBe('true')

    await wrapper.find('[data-view-mode="grid"]').trigger('click')
    expect(wrapper.find('.project-list__rows').classes()).toContain('is-grid')
    expect(wrapper.findAll('.project-row.is-grid')).toHaveLength(2)
    expect(wrapper.find('[data-view-mode="grid"]').attributes('aria-pressed')).toBe('true')
    expect(localStorage.getItem('zhiyi.projects.view-mode.v1')).toBe('grid')

    await wrapper.find('[data-view-mode="list"]').trigger('click')
    expect(wrapper.find('.project-list__rows').classes()).not.toContain('is-grid')
    expect(localStorage.getItem('zhiyi.projects.view-mode.v1')).toBe('list')
  })

  it('opens Create Mission and Mission Workspace through named routes', async () => {
    const { wrapper, router } = await mountPage()
    await wrapper.find('.project-list__create').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('CreateMission')
    await router.push('/agentos/acg')
    await wrapper.find('.project-row').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('MissionWorkspace')
    expect(router.currentRoute.value.params.missionId).toBe('mission_1')
  })

  it('restores Mission actions from the row context menu and uses missionId', async () => {
    const archiveMission = vi.spyOn(agentosApi, 'archiveMission').mockResolvedValue({
      missionId: 'mission_1', recordState: 'archived', affectedRunCount: 1
    })
    const { wrapper } = await mountPage()

    await wrapper.find('.project-row').trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    const menu = document.body.querySelector<HTMLElement>('#project-action-menu')
    const archive = menu?.querySelector<HTMLButtonElement>('[data-action="archive"]')
    expect(menu?.textContent).toContain('归档任务')
    expect(menu?.textContent).toContain('删除任务')
    expect(archive?.disabled).toBe(false)

    archive?.click()
    await flushPromises()

    expect(archiveMission).toHaveBeenCalledWith('mission_1')
    expect(archiveMission).not.toHaveBeenCalledWith('run_1')
    expect(wrapper.findAll('.project-row')).toHaveLength(1)
  })

  it('confirms deletion and disables destructive actions for an active Mission', async () => {
    const deleteMission = vi.spyOn(agentosApi, 'deleteMission').mockResolvedValue({
      missionId: 'mission_1', recordState: 'deleted', affectedRunCount: 1
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const { wrapper } = await mountPage()

    await wrapper.findAll('.project-row')[0].trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    const menu = document.body.querySelector<HTMLElement>('#project-action-menu')
    const remove = menu?.querySelector<HTMLButtonElement>('[data-action="delete"]')
    remove?.click()
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('执行审计事实仍会保留'),
      '删除任务',
      expect.objectContaining({ confirmButtonText: '删除' })
    )
    expect(deleteMission).toHaveBeenCalledWith('mission_1')
    expect(deleteMission).not.toHaveBeenCalledWith('run_1')

    await wrapper.findAll('.project-row')[0].trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    const activeMenu = document.body.querySelector<HTMLElement>('#project-action-menu')
    const activeArchive = activeMenu?.querySelector<HTMLButtonElement>('[data-action="archive"]')
    expect(activeArchive?.disabled).toBe(true)
    expect(activeArchive?.title).toContain('运行中的任务')
  })
})
