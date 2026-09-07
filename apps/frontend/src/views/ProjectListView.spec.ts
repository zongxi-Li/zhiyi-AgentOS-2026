import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import { ElMessageBox } from 'element-plus'
import { downloadFile } from '@/utils/export'
import ProjectListView from './ProjectListView.vue'

vi.mock('@/utils/export', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/export')>()
  return { ...actual, downloadFile: vi.fn() }
})

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

const mountPage = async (items = missions) => {
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
  vi.spyOn(agentosApi, 'listMissions').mockResolvedValue({ items, total: items.length, page: 1, pageSize: 100 })
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
    document.body.querySelector('#project-export-menu')?.remove()
    localStorage.removeItem('zhiyi.projects.view-mode.v1')
    vi.mocked(downloadFile).mockClear()
    vi.restoreAllMocks()
  })

  it('renders one row per Mission instead of one row per Run', async () => {
    const { wrapper } = await mountPage()
    expect(agentosApi.listMissions).toHaveBeenCalledWith({ page: 1, pageSize: 100 }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findAll('.project-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('1 次运行')
    expect(wrapper.text()).toContain('2 次运行')
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
    expect(router.currentRoute.value.query.runId).toBe('run_1')
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

    const deleteMessage = vi.mocked(ElMessageBox.confirm).mock.calls[0]?.[0] as any
    expect(deleteMessage).toEqual(expect.objectContaining({
      type: 'div',
      props: expect.objectContaining({ class: 'mission-delete-message' })
    }))
    const deleteMessageChildren = deleteMessage.children as Array<{ children?: unknown }>
    expect(deleteMessageChildren.map(child => child.children).join(' ')).toContain('设备人员规划')
    expect(deleteMessageChildren.map(child => child.children).join(' ')).not.toContain('目标')
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.anything(),
      '删除任务',
      expect.objectContaining({
        confirmButtonText: '删除',
        customClass: 'apple-delete-message-box',
        modalClass: 'apple-delete-message-box__overlay',
        confirmButtonClass: 'apple-delete-confirm-button',
        cancelButtonClass: 'apple-delete-cancel-button',
        roundButton: true
      })
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

  it('allows deletion when a failed Mission only exposes its terminal mission status', async () => {
    const failedMission = {
      missionId: 'mission_failed', userId: 'user_1', title: '失败的任务', description: '失败任务正文不应出现在确认框', status: 'failed',
      latestRunId: 'run_failed', latestRunStatus: null, createdAt: '2026-08-28T00:00:00Z', updatedAt: '2026-08-28T03:00:00Z', runCount: 1
    }
    const deleteMission = vi.spyOn(agentosApi, 'deleteMission').mockResolvedValue({
      missionId: 'mission_failed', recordState: 'deleted', affectedRunCount: 1
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const { wrapper } = await mountPage([failedMission])

    await wrapper.find('.project-row').trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    const menu = document.body.querySelector<HTMLElement>('#project-action-menu')
    const remove = menu?.querySelector<HTMLButtonElement>('[data-action="delete"]')

    expect(remove?.disabled).toBe(false)
    remove?.click()
    await flushPromises()

    expect(deleteMission).toHaveBeenCalledWith('mission_failed')
    expect(wrapper.findAll('.project-row')).toHaveLength(0)
  })

  it('exports the filtered project list from the toolbar menu as CSV', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.find('.project-list__export').attributes('disabled')).toBeUndefined()

    await wrapper.find('.project-list__export').trigger('click')
    await flushPromises()
    const menu = document.body.querySelector<HTMLElement>('#project-export-menu')
    expect(menu?.textContent).toContain('Markdown')
    expect(menu?.textContent).toContain('JSON')

    document.body.querySelector<HTMLButtonElement>('#project-export-menu [data-format="csv"]')?.click()
    await flushPromises()

    expect(vi.mocked(downloadFile)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(downloadFile)).toHaveBeenCalledWith(
      expect.stringContaining('医院门诊优化'),
      expect.stringMatching(/^工程项目导出_.+\.csv$/),
      expect.stringContaining('text/csv')
    )
    const [content] = vi.mocked(downloadFile).mock.calls[0]
    expect(content).toContain('mission_2')
    expect(content).toContain('运行次数')
  })

  it('export honors the active search filter', async () => {
    const { wrapper } = await mountPage()
    await wrapper.find('input[type="search"]').setValue('医院')
    await wrapper.find('.project-list__export').trigger('click')
    await flushPromises()

    document.body.querySelector<HTMLButtonElement>('#project-export-menu [data-format="json"]')?.click()
    await flushPromises()

    expect(vi.mocked(downloadFile)).toHaveBeenCalledTimes(1)
    const [content] = vi.mocked(downloadFile).mock.calls[0]
    expect(content).toContain('mission_2')
    expect(content).not.toContain('mission_1')
  })

  it('disables export when there is nothing to export', async () => {
    const { wrapper } = await mountPage([])
    expect(wrapper.find('.project-list__export').attributes('disabled')).toBeDefined()
  })

  it('exports a single mission with its run history from the row action menu', async () => {
    const listWorkflowRuns = vi.spyOn(agentosApi, 'listWorkflowRuns').mockResolvedValue({
      items: [{
        missionId: 'mission_2', runId: 'run_2', workflowId: 'wf_1', status: 'failed', phase: 'executing',
        message: '步骤 quality_review 失败', percent: null, totalSteps: 38, pendingSteps: 0, runningSteps: 0,
        waitingReviewSteps: 0, retryingSteps: 0, failedSteps: 2, completedSteps: 31, cancelledSteps: 0,
        currentStepId: null, activeStepIds: [], startedAt: '2026-09-06T10:00:00Z', updatedAt: '2026-09-06T11:00:00Z',
        progress: 0.8, percentage: 80
      }],
      total: 1, page: 1, pageSize: 100
    })
    const { wrapper } = await mountPage()

    await wrapper.findAll('.project-row')[1].trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    const actionMenu = document.body.querySelector<HTMLElement>('#project-action-menu')
    expect(actionMenu?.textContent).toContain('导出任务数据')

    document.body.querySelector<HTMLButtonElement>('#project-action-menu [data-action="export"]')?.click()
    await flushPromises()
    const exportMenu = document.body.querySelector<HTMLElement>('#project-export-menu')
    expect(exportMenu?.textContent).toContain('医院门诊优化')

    document.body.querySelector<HTMLButtonElement>('#project-export-menu [data-format="json"]')?.click()
    await flushPromises()

    expect(listWorkflowRuns).toHaveBeenCalledWith({ missionId: 'mission_2', page: 1, pageSize: 100 })
    expect(vi.mocked(downloadFile)).toHaveBeenCalledTimes(1)
    const [content, filename] = vi.mocked(downloadFile).mock.calls[0]
    expect(filename).toMatch(/^任务导出_医院门诊优化_.+\.json$/)
    expect(content).toContain('run_2')
    expect(content).toContain('步骤 quality_review 失败')
    expect(content).toContain('"statusLabel": "失败"')
  })

  it('exports mission-level CSV containing run steps and failure counts', async () => {
    vi.spyOn(agentosApi, 'listWorkflowRuns').mockResolvedValue({
      items: [{
        missionId: 'mission_1', runId: 'run_1', workflowId: 'wf_1', status: 'completed', phase: 'completed',
        message: '', percent: null, totalSteps: 12, pendingSteps: 0, runningSteps: 0,
        waitingReviewSteps: 0, retryingSteps: 0, failedSteps: 0, completedSteps: 12, cancelledSteps: 0,
        currentStepId: null, activeStepIds: [], startedAt: '2026-08-28T00:30:00Z', updatedAt: '2026-08-28T01:00:00Z',
        progress: 1, percentage: 100
      }],
      total: 1, page: 1, pageSize: 100
    })
    const { wrapper } = await mountPage()

    await wrapper.findAll('.project-row')[0].trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    document.body.querySelector<HTMLButtonElement>('#project-action-menu [data-action="export"]')?.click()
    await flushPromises()
    document.body.querySelector<HTMLButtonElement>('#project-export-menu [data-format="csv"]')?.click()
    await flushPromises()

    const [content] = vi.mocked(downloadFile).mock.calls[0]
    expect(content).toContain('任务概览')
    expect(content).toContain('运行记录')
    expect(content).toContain('"run_1","已完成","完成","12","12","0"')
  })

  it('exports a mission without runs as an empty run list', async () => {
    vi.spyOn(agentosApi, 'listWorkflowRuns').mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 100 })
    const idleMission = {
      missionId: 'mission_idle', userId: 'user_1', title: '还没有运行的任务', description: '', status: 'created',
      latestRunId: null, latestRunStatus: null, createdAt: '2026-09-07T00:00:00Z', updatedAt: '2026-09-07T00:00:00Z', runCount: 0
    }
    const { wrapper } = await mountPage([idleMission])

    await wrapper.find('.project-row').trigger('contextmenu', { clientX: 120, clientY: 160 })
    await flushPromises()
    document.body.querySelector<HTMLButtonElement>('#project-action-menu [data-action="export"]')?.click()
    await flushPromises()
    document.body.querySelector<HTMLButtonElement>('#project-export-menu [data-format="md"]')?.click()
    await flushPromises()

    const [content] = vi.mocked(downloadFile).mock.calls[0]
    expect(content).toContain('该任务暂无运行记录')
  })
})
