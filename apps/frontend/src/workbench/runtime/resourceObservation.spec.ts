import { afterEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import { loadResourceObservation } from './resourceObservation'

describe('loadResourceObservation', () => {
  afterEach(() => vi.restoreAllMocks())

  it('joins real profiles with V2 attempt bindings without changing health', async () => {
    vi.spyOn(agentosApi, 'listResources').mockResolvedValue({
      total: 1,
      items: [{
        profile: {
          resourceId: 'native_general_agent', resourceType: 'agent', deploymentTier: 'edge', capabilities: ['general'], domains: [], labels: [],
          costMetadata: {}, capacity: 1, enabled: true, metadata: {}, version: 1
        },
        snapshot: {
          resourceId: 'native_general_agent', observedAt: '2026-08-29T00:00:00Z', availableSlots: 1,
          utilization: 0, healthStatus: 'unknown', metrics: {}
        },
        snapshotVersion: 1
      }]
    })
    vi.spyOn(agentosApi, 'getExecutionTree').mockResolvedValue({
      nodes: [{
        task: { taskId: 'task_1', missionId: 'mission_1', semanticTaskKey: 'equipment_staff_plan', title: 'Equipment', objective: 'Plan' },
        acgNodeId: 'node_1',
        attempts: [{
          attempt: { attemptId: 'attempt_1', runId: 'run_1', taskId: 'task_1', status: 'succeeded', attemptNumber: 1 },
          resourceUse: {
            acgNodeId: 'node_1', resourceId: 'native_general_agent',
            agentId: 'native_general_agent', modelId: 'runtime-default', deploymentTier: 'edge'
          },
          executions: []
        }]
      }]
    } as any)

    const result = await loadResourceObservation('run_1')

    expect(result.runId).toBe('run_1')
    expect(result.attemptCount).toBe(1)
    expect(result.bindings[0]).toMatchObject({
      semanticTaskKey: 'equipment_staff_plan',
      resourceId: 'native_general_agent',
      agentId: 'native_general_agent',
      modelId: 'runtime-default',
      deploymentTier: 'edge'
    })
    expect(result.items[0].snapshot.healthStatus).toBe('unknown')
  })
})
