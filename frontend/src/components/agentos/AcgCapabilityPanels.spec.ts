import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import AcgExecutionContractBar from './AcgExecutionContractBar.vue'
import AcgOperationalInspector from './AcgOperationalInspector.vue'
import IdentityHealthStrip from './IdentityHealthStrip.vue'

const view = {
  runId: 'run_1', status: 'running', engine: 'acg', acgBlueprint: null, completedStepIds: [], activeStepIds: [], stepStates: [],
  provenance: { productions: [], consumptions: [], interactions: [] }, interactions: [], contractViolations: [], recoveryTrace: [],
  scheduleTrace: [], deliverables: [], finalReport: null,
  lowEntropyMetrics: { averageSavingRatio: 0, effectiveSavingRatio: 0, tokensAvailable: 0, tokensDelivered: 0, tokensSaved: 0, recoveryCount: 0, interactionCount: 0, contractViolationCount: 0, integrityStatus: 'valid' },
  executionTree: {
    run: { runId: 'run_1', taskId: 'task_1', blueprintId: 'blueprint_1', status: 'running', graphVersion: 2, metadata: {} },
    blueprint: { blueprintId: 'blueprint_1', taskId: 'task_1', version: 2, graphId: 'graph_1', graph: {}, metadata: {} },
    nodes: [], operational: null
  },
  operational: {
    package: { packageId: 'package_123456789', packageVersion: 2, checksum: 'checksum_123456789', blueprintHash: 'blueprint_hash_123456789' },
    lineage: { parentRunId: 'run_parent', supersedesRunId: 'run_old', sourcePatchId: 'patch_1' },
    nodeExecutions: [{ operationId: 'operation_1', executionInstanceId: 'instance_1', runId: 'run_1', stepId: 'step_1', attemptId: 'attempt_1', phase: 'committed', artifactRefs: { output: 'artifact_1' }, auditRef: 'audit_1', commitId: 'commit_1', loopPath: [1] }],
    controlFrames: [{ type: 'parallel', status: 'joined' }], communicationRefs: ['message_1'], memoryRefs: ['memory_1'], evidenceRefs: ['evidence_1'],
    leaseStatuses: { lease_1: 'active' }, loopIterations: { loop_1: 2 }, consensusResults: { consensus_1: { decision: 'accepted' } },
    debateSessions: { debate_1: { round: 2 } }, recoveryOutcome: { action: 'resume', status: 'succeeded' }
  },
  identityProjection: { status: 'available' }
} as any

describe('ACG capability panels', () => {
  it('shows package, Blueprint and Run lineage identities', () => {
    const wrapper = mount(AcgExecutionContractBar, { props: { view }, global: { plugins: [ElementPlus] } })
    expect(wrapper.text()).toContain('package_123456789')
    expect(wrapper.text()).toContain('blueprint_1')
    expect(wrapper.text()).toContain('父 Run')
    expect(wrapper.text()).toContain('patch_1')
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
