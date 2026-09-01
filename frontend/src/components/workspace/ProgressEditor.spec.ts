import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workflowApi } from '@/services/api/workflow'
import ProgressEditor from './ProgressEditor.vue'
import type { MissionWorkspaceProjection, WorkspaceEntry } from '@/services/api/agentos'
import type { WorkflowProgress } from '@/services/api/workflow'

vi.mock('@/services/api/workflow', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/api/workflow')>()
  return { ...actual, workflowApi: { ...actual.workflowApi, getWorkflowProgress: vi.fn() } }
})

const getProgress = vi.mocked(workflowApi.getWorkflowProgress)

const progress = (overrides: Partial<WorkflowProgress> = {}): WorkflowProgress => ({
  taskId: 'task_1', runId: 'run_1', workflowId: 'workflow_1', status: 'running',
  phase: 'executing', message: 'running risk review', percent: 42.86,
  totalSteps: 7, pendingSteps: 3, runningSteps: 1, waitingReviewSteps: 0,
  retryingSteps: 0, failedSteps: 0, completedSteps: 3, cancelledSteps: 0,
  currentStepId: 'risk_detect', activeStepIds: ['risk_detect'],
  startedAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:01Z',
  progress: 0.4286, percentage: 42.86, ...overrides
})

const entry = (): WorkspaceEntry => ({
  entryId: 'overview:progress',
  kind: 'progress',
  name: '运行进度',
  title: '运行进度',
  group: 'overview',
  displayOrder: -1
})

const projection = (): MissionWorkspaceProjection => ({
  missionId: 'mission_1',
  entries: [],
  graphNodes: [
    { acgNodeId: 'risk_detect', nodeType: 'task', name: '风险检测', semanticTaskKey: 'risk:detection', displayOrder: 1 },
    { acgNodeId: 'node_unknown', nodeType: 'task', name: 'node_unknown', semanticTaskKey: null, displayOrder: 2 }
  ]
}) as MissionWorkspaceProjection

const mountEditor = async (runId: string | null = 'run_1') => {
  const wrapper = mount(ProgressEditor, {
    props: { entry: entry(), projection: projection(), runId }
  })
  if (runId) await vi.waitFor(() => expect(getProgress).toHaveBeenCalled())
  return wrapper
}

describe('ProgressEditor', () => {
  beforeEach(() => {
    getProgress.mockClear()
  })

  it('renders the runtime progress bar with live polling data', async () => {
    getProgress.mockResolvedValue(progress())
    const wrapper = await mountEditor()

    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('42.86')
    expect(wrapper.text()).toContain('42.86%')
  })

  it('shows the empty state without a run instead of polling', () => {
    const wrapper = mount(ProgressEditor, {
      props: { entry: entry(), projection: projection(), runId: null }
    })

    expect(getProgress).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('当前 Mission 尚无可展示的 Run。')
  })

  it('restarts polling when the active run changes', async () => {
    getProgress.mockResolvedValue(progress())
    const wrapper = await mountEditor()

    await wrapper.setProps({ runId: 'run_2' })
    await vi.waitFor(() => expect(getProgress).toHaveBeenLastCalledWith('run_2', expect.anything()))
  })

  it('maps active steps to clickable semantic tasks and plain labels otherwise', async () => {
    getProgress.mockResolvedValue(progress({
      activeStepIds: ['risk_detect', 'node_unknown'],
      currentStepId: 'risk_detect'
    }))
    const wrapper = await mountEditor()
    await vi.waitFor(() => expect(wrapper.text()).toContain('进行中的步骤'))

    const chips = wrapper.findAll('.progress-editor__chip')
    expect(chips).toHaveLength(2)
    expect(chips[0].text()).toBe('风险检测')
    expect(chips[0].attributes('disabled')).toBeUndefined()
    await chips[0].trigger('click')
    expect(wrapper.emitted('openSemanticTask')).toEqual([['risk:detection']])

    expect(chips[1].text()).toBe('node_unknown')
    expect(chips[1].attributes('disabled')).toBeDefined()
  })

  it('renders the step counter grid', async () => {
    getProgress.mockResolvedValue(progress({ failedSteps: 1 }))
    const wrapper = await mountEditor()

    const labels = wrapper.findAll('.progress-editor__counter dt').map(node => node.text())
    expect(labels).toEqual(['总步骤', '已完成', '运行中', '待执行', '待评审', '重试中', '已失败', '已取消'])
    const failed = wrapper.findAll('.progress-editor__counter dd')[6]
    expect(failed.text()).toBe('1')
  })

  it('surfaces sync errors instead of a fake zero progress', async () => {
    getProgress.mockRejectedValue(new Error('offline'))
    const wrapper = await mountEditor()
    await vi.waitFor(() => expect(wrapper.text()).toContain('进度同步暂时中断'))

    expect(wrapper.find('[role="status"]').text()).toContain('进度同步暂时中断')
    expect(wrapper.text()).not.toContain('0%')
  })
})
