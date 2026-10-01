import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { workflowApi } from '@/services/api/workflow'
import AcgExecutionContractBar from './AcgExecutionContractBar.vue'
import AcgOperationalInspector from './AcgOperationalInspector.vue'
import AcgResourceInspector from './AcgResourceInspector.vue'
import IdentityHealthStrip from './IdentityHealthStrip.vue'

const view = {
  runId: 'run_1', status: 'running', engine: 'acg', acgBlueprint: null, completedStepIds: [], activeStepIds: [], stepStates: [],
  provenance: { productions: [], consumptions: [], interactions: [] }, interactions: [], contractViolations: [], recoveryTrace: [],
  scheduleTrace: [], deliverables: [], finalReport: null,
  lowEntropyMetrics: { averageSavingRatio: 0, effectiveSavingRatio: 0, tokensAvailable: 0, tokensDelivered: 0, tokensSaved: 0, recoveryCount: 0, interactionCount: 0, contractViolationCount: 0, integrityStatus: 'valid' },
  executionTree: {
    run: { runId: 'run_1', taskId: 'task_1', blueprintId: 'blueprint_1', status: 'running', graphVersion: 2, metadata: {} },
    graph: { graphId: 'graph_1', graphVersion: 2, nodes: [], edges: [] },
    nodes: [], operational: null
  },
  lineage: { parentRunId: 'run_parent', supersedesRunId: 'run_old' },
  lifecycles: [{ stepId: 'step_1', attemptId: 'attempt_1', phase: 'committed', sequence: 0 }],
  identityProjection: { status: 'available' }
} as any

describe('ACG capability panels', () => {
  it('shows package, Blueprint and Run lineage identities', () => {
    const wrapper = mount(AcgExecutionContractBar, { props: { view }, global: { plugins: [ElementPlus] } })
    expect(wrapper.text()).not.toContain('Package')
    expect(wrapper.text()).toContain('graph_1')
    expect(wrapper.text()).toContain('父 Run')
    expect(wrapper.text()).not.toContain('patch_1')
  })

  it('renders lifecycle and exposes control, communication and recovery tabs', async () => {
    const wrapper = mount(AcgOperationalInspector, {
      props: { view, auditEvents: [], patchRefs: ['patch_1'] }, global: { plugins: [ElementPlus] }
    })
    expect(wrapper.text()).toContain('step_1')
    expect(wrapper.text()).toContain('已提交')
    expect(wrapper.text()).toContain('控制协同')
    expect(wrapper.text()).toContain('通信上下文')
    expect(wrapper.text()).toContain('恢复审计')
    expect(wrapper.findAll('.el-tabs__item')).toHaveLength(5)
    expect(wrapper.findAll('.el-tabs__item').some(item => item.text().includes('资源'))).toBe(false)
  })

  it('summarizes control and context capabilities without hiding their details', async () => {
    const wrapper = mount(AcgOperationalInspector, {
      props: { view, auditEvents: [], patchRefs: [] }, global: { plugins: [ElementPlus] }
    })

    await wrapper.findAll('.el-tabs__item').find(item => item.text().includes('控制协同'))!.trigger('click')
    expect(wrapper.text()).toContain('审核对象与原因由审核面板展示')
    expect(wrapper.text()).not.toContain('parallel')
    await wrapper.findAll('.el-tabs__item').find(item => item.text().includes('通信上下文'))!.trigger('click')
    expect(wrapper.text()).toContain('Context Inspector')
    expect(wrapper.text()).not.toContain('lease_1')

  })

  it('uses a consistent zero-state summary when operational data is absent', async () => {
    const emptyView = { ...view, lifecycles: [] }
    const wrapper = mount(AcgOperationalInspector, {
      props: { view: emptyView, auditEvents: [], patchRefs: [] }, global: { plugins: [ElementPlus] }
    })

    await wrapper.findAll('.el-tabs__item').find(item => item.text().includes('控制协同'))!.trigger('click')
    expect(wrapper.findAll('.summary-card')).toHaveLength(0)
    expect(wrapper.findAll('.empty').length).toBeGreaterThanOrEqual(1)
  })

  it('keeps unknown API capacity unknown in the read-only resource panel', async () => {
    vi.spyOn(workflowApi, 'listRunResourceCalls').mockResolvedValue({
      runId: 'run_1', items: [], nextCursor: undefined, total: 0
    })
    const wrapper = mount(AcgResourceInspector, {
      props: {
        runId: 'run_1',
        usage: {
          runId: 'run_1',
          capability: { provider: 'test', model: 'model', source: 'unknown', features: {} },
          usage: {
            inputTokens: 100, outputTokens: 40, cacheReadTokens: 25,
            cacheWriteTokens: 0, reasoningTokens: 10, totalTokens: 140,
            callCount: 1, retryCount: 0, latencyMs: 120, cacheHitRatio: 0.25
          },
          contextPressure: {
            current: null, peak: null, currentInputTokens: 100, peakInputTokens: 100,
            contextWindowTokens: null, source: 'unknown'
          },
          composition: {
            materialManifestCount: 1, materialFragmentCount: 5, taskCount: 2,
            completedTaskCount: 1, persistedResultFragmentCount: 5,
            reducerManifestCount: 1, chapterCount: 0, artifactCount: 0,
            assemblyComplete: false, taskProgress: 0.5
          },
          scheduler: { activeSlots: 1, queueDepth: 0, checkpointCount: 0, recoveryCount: 0 }
        } as any
      },
      global: { plugins: [ElementPlus] }
    })

    await flushPromises()

    expect(wrapper.text()).toContain('上限未声明')
    expect(wrapper.text()).toContain('100 Token')
    expect(wrapper.text()).toContain('推理 Token 已包含在供应商输出明细中')
    expect(wrapper.find('.resource-panel').exists()).toBe(true)
  })

  it('marks retained health data stale without hiding backlog facts', () => {
    const wrapper = mount(IdentityHealthStrip, {
      props: {
        health: {
          status: 'degraded', source: 'agentos-v2', backlogCount: 7, failedCount: 2, oldestEventAt: '2026-08-22T00:00:00Z',
          unappliedEventCount: 3, inboxBacklog: 2, outboxBacklog: 2,
          startupReconciliation: { examinedTasks: 5, examinedRuns: 6, repairedTasks: 1, repairedRuns: 1, replayedEvents: 4, failureCount: 1 }
        },
        loading: false, error: 'Identity 健康度暂时无法同步', lastUpdatedAt: '2026-08-22T00:01:00Z'
      },
      global: { plugins: [ElementPlus] }
    })
    expect(wrapper.text()).toContain('数据已过期')
    expect(wrapper.text()).toContain('Backlog7')
    expect(wrapper.text()).toContain('保留上次结果')
  })
})
