import { flushPromises } from '@vue/test-utils'
import { effectScope, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { usePlanningSnapshots } from './planningSnapshots'
import type { CopilotInitialPlan } from '@/services/api/agentos/api/copilot'

const plan = (planVersion: number): CopilotInitialPlan => ({
  planVersion, commitId: null, commitmentRevision: null, objective: '审查仓库', constraints: [], expectedArtifacts: [],
  tasks: [{ key: 'read', title: '读取', objective: '检查源码', rationale: '', acceptanceCriteria: [],
    sourceRefs: [], capabilities: planVersion === 1 ? ['read'] : ['read', 'analyze'] },
    ...(planVersion > 1 ? [{ key: 'review', title: '复核', objective: '形成结论', rationale: '',
      acceptanceCriteria: [], sourceRefs: [], capabilities: ['analyze'] }] : [])],
  relations: planVersion === 1 ? [] : [{ sourceKey: 'read', targetKey: 'review', relationType: 'depends_on' }],
})
const setup = () => {
  const input = { runId: ref<string | null>('run'), planVersion: ref<number | null>(2),
    previousVersion: ref<number | null>(1), identity: ref('graph:v2'), enabled: ref(true),
    historical: ref(false), comparing: ref(false) }
  const api = { getPlanSnapshot: vi.fn(async (runId: string, version?: number | null) => ({ runId, plan: plan(version || 2) })) }
  const scope = effectScope()
  const state = scope.run(() => usePlanningSnapshots(input, api))!
  return { input, api, scope, state }
}

describe('accepted ACG snapshots', () => {
  it('follows the selected ACG version, preserves immutable snapshots and compares planning changes', async () => {
    const { input, api, scope, state } = setup()
    await flushPromises()
    expect(state.plan.value?.planVersion).toBe(2)
    input.comparing.value = true
    await flushPromises()
    expect(state.difference.value).toMatchObject({ addedNodeIds: ['review'], updatedNodeIds: ['read'] })
    input.historical.value = true
    input.planVersion.value = 1
    input.identity.value = 'graph:v1'
    await flushPromises()
    expect(state.plan.value?.tasks).toHaveLength(1)
    input.identity.value = 'graph:v3'
    await flushPromises()
    expect(state.plan.value?.planVersion).toBe(1)
    expect(api.getPlanSnapshot).toHaveBeenCalledTimes(2)
    input.historical.value = false
    input.planVersion.value = 3
    await flushPromises()
    expect(state.plan.value?.planVersion).toBe(3)
    scope.stop()
  })

  it('discards a late current response when the user pins an earlier ACG version', async () => {
    const { input, api, scope, state } = setup()
    await flushPromises()
    let finish!: (value: { runId: string; plan: CopilotInitialPlan }) => void
    api.getPlanSnapshot.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    input.planVersion.value = 3
    input.identity.value = 'graph:v3'
    await flushPromises()
    input.planVersion.value = 1
    input.historical.value = true
    input.identity.value = 'graph:v1'
    await flushPromises()
    finish({ runId: 'run', plan: plan(3) })
    await flushPromises()
    expect(state.plan.value?.planVersion).toBe(1)
    expect(state.loading.value).toBe(false)
    scope.stop()
  })

  it('does not substitute the initial plan when a historical mapping is missing or another run responds', async () => {
    const { input, api, scope, state } = setup()
    await flushPromises()
    input.historical.value = true
    input.planVersion.value = null
    await flushPromises()
    expect(state.plan.value).toBeNull()
    expect(state.error.value).toContain('没有登记')
    api.getPlanSnapshot.mockResolvedValueOnce({ runId: 'other', plan: plan(3) })
    input.planVersion.value = 3
    await flushPromises()
    expect(state.plan.value).toBeNull()
    expect(state.error.value).toContain('读取失败')
    scope.stop()
  })
})
