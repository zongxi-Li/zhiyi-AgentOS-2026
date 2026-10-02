import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentOsRunSummaryCard from './AgentOsRunSummaryCard.vue'
import type { WorkflowProgress, WorkflowRun } from '@/services/api/workflow'

const progress: WorkflowProgress = {
  taskId: 'task_1', runId: 'run_1', workflowId: 'workflow_1', status: 'running',
  phase: 'executing', message: 'running', percent: 50, totalSteps: 4, pendingSteps: 1,
  runningSteps: 1, waitingReviewSteps: 0, retryingSteps: 0, failedSteps: 0,
  completedSteps: 2, cancelledSteps: 0, currentStepId: 'step_3', activeStepIds: ['step_3'],
  startedAt: '2026-08-19T00:00:00Z', updatedAt: '2026-08-19T00:01:00Z', progress: 0.5, percentage: 50
}

const run: WorkflowRun = {
  runId: 'run_1', taskId: 'task_1', workflowId: 'workflow_1', domain: 'native', status: 'running',
  steps: [], skippedStepIds: ['step_2'], graphVersion: 3
}

describe('AgentOsRunSummaryCard', () => {
  it('projects only 执行运行时 v2 run, graph and audit facts', () => {
    const wrapper = mount(AgentOsRunSummaryCard, {
      props: {
        progress,
        run,
        view: {
          status: 'running', graphVersion: 3, stepStates: [], interactions: [{ interactionId: 'i1' }],
          recoveryTrace: [], scheduleTrace: [], contractViolations: [], lowEntropyMetrics: { recoveryCount: 2 }
        } as any,
        events: [{ eventId: 'event_1', runId: 'run_1', eventType: 'STEP_STARTED' }]
      }
    })
    expect(wrapper.text()).toContain('运行态摘要')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).not.toContain('GraphPatch 引用')
    expect(wrapper.text()).toContain('2 次恢复')
    expect(wrapper.text()).not.toContain('bindingSwitchCount')
    expect(wrapper.text()).not.toContain('Runtime Graph')
  })

  it('renders an honest empty state instead of invented metrics', () => {
    const wrapper = mount(AgentOsRunSummaryCard)
    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).toContain('等待可验证的运行审计事件')
  })
})
