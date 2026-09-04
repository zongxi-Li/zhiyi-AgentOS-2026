import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi, type MissionWorkspaceProjection, type WorkspaceEntry } from '@/services/api/agentos'
import { RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import TaskEditor from './TaskEditor.vue'

const task: WorkspaceEntry = {
  entryId: 'task:design', kind: 'task', name: '系统架构设计', group: 'steps', displayOrder: 0,
  semanticTaskKey: 'design', taskId: 'task_1', acgNodeId: 'node_1', runId: 'run_1',
  metadata: { outputRef: 'output:node_1', outputSummary: '架构设计完成' },
}

const projection: MissionWorkspaceProjection = {
  mission: {
    missionId: 'mission_1', userId: 'user_1', goal: 'test', description: '', metadata: {},
    createdAt: '2026-09-04T00:00:00Z', updatedAt: '2026-09-04T00:00:00Z', status: 'running',
  },
  activeRun: {
    runId: 'run_1', status: 'running', createdAt: '2026-09-04T00:00:00Z', isActive: true,
  },
  activeGraph: null, runs: [], entries: [task], diagnostics: [],
  graphNodes: [{ acgNodeId: 'node_1', nodeType: 'step', name: '系统架构设计', semanticTaskKey: 'design', displayOrder: 0 }],
}

const mountEditor = (runtimeStore: RunRuntimeStore | null = null) => mount(TaskEditor, {
  props: { entry: task, projection, graphNodes: projection.graphNodes, runtimeObservation: null, runtimeStore },
})

describe('TaskEditor stage output', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads and displays a persisted node result without calling it a formal Artifact', async () => {
    vi.spyOn(agentosApi, 'getRunOutput').mockResolvedValue({
      runId: 'run_1', outputRef: 'output:node_1', content: { summary: '架构方案', decision: '事件驱动' },
    })
    const wrapper = mountEditor()
    await flushPromises()

    expect(agentosApi.getRunOutput).toHaveBeenCalledWith('run_1', 'output:node_1', expect.anything())
    expect(wrapper.get('[data-testid="task-stage-output"]').text()).toContain('架构方案')
    expect(wrapper.text()).toContain('STAGE OUTPUT / 阶段结果')
  })

  it('prefers the current live stream while a node is executing', async () => {
    vi.spyOn(agentosApi, 'getRunOutput').mockResolvedValue({
      runId: 'run_1', outputRef: 'output:node_1', content: { summary: '旧结果' },
    })
    const runtimeStore = new RunRuntimeStore('run_1')
    runtimeStore.apply({
      eventId: 'evt_1', eventType: 'model.output.delta', runId: 'run_1', nodeId: 'node_1',
      attemptId: 'attempt_1', sequence: 1, payload: { delta: '正在生成的新阶段结果' },
    })
    await new Promise(resolve => setTimeout(resolve, 20))
    const wrapper = mountEditor(runtimeStore)
    await flushPromises()

    expect(wrapper.get('[data-testid="task-stage-output"]').text()).toContain('正在生成的新阶段结果')
    expect(wrapper.get('[data-testid="task-stage-output"]').text()).not.toContain('旧结果')
  })
})
