import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'
import { agentosApi, type GraphProjection } from '@/services/api/agentos'
import type { CopilotInitialPlan } from '@/services/api/agentos/api/copilot'
import { compareGraphs } from './graphVersions'

export const planningGraph = (plan: CopilotInitialPlan): GraphProjection => {
  const keys = new Set(plan.tasks.map(task => task.key))
  return {
    graphId: `plan:${plan.commitId || plan.planVersion}`, graphVersion: plan.planVersion,
    nodes: plan.tasks.map(task => ({ nodeId: task.key, nodeType: 'step', name: task.title, goal: task.objective,
      description: JSON.stringify([task.rationale, task.acceptanceCriteria]),
      display: { allowedSkills: task.capabilities } })),
    edges: (plan.relations || []).filter(relation => relation.relationType === 'depends_on'
      && keys.has(relation.sourceKey) && keys.has(relation.targetKey)).map(relation => ({
      edgeId: JSON.stringify([relation.sourceKey, relation.targetKey]), sourceId: relation.sourceKey,
      targetId: relation.targetKey, edgeType: 'dependency',
    })),
  }
}

/** Accepted, Run-scoped snapshots. The initial consent plan is never substituted for a revision. */
export function usePlanningSnapshots(input: {
  runId: Readonly<Ref<string | null>>
  planVersion: Readonly<Ref<number | null>>
  previousVersion: Readonly<Ref<number | null>>
  identity: Readonly<Ref<string>>
  enabled: Readonly<Ref<boolean>>
  historical: Readonly<Ref<boolean>>
  comparing: Readonly<Ref<boolean>>
}, api: Pick<typeof agentosApi, 'getPlanSnapshot'> = agentosApi) {
  const plan = shallowRef<CopilotInitialPlan | null>(null)
  const previous = shallowRef<CopilotInitialPlan | null>(null)
  const loading = ref(false)
  const error = ref('')
  const cache = new Map<string, CopilotInitialPlan | null>()
  let controller: AbortController | undefined
  let request = 0
  const refresh = async () => {
    controller?.abort()
    const current = ++request
    const runId = input.runId.value
    plan.value = null
    previous.value = null
    error.value = ''
    loading.value = false
    if (!input.enabled.value || !runId) return
    if (input.historical.value && input.planVersion.value == null) {
      error.value = '该 RGraph 版本没有登记对应的 ACG 版本。'
      return
    }
    const local = new AbortController()
    controller = local
    loading.value = true
    const read = async (version: number | null) => {
      const key = JSON.stringify([runId, version, version == null ? input.identity.value : null])
      if (cache.has(key)) return cache.get(key)!
      const result = await api.getPlanSnapshot(runId, version, { signal: local.signal })
      if (local.signal.aborted || current !== request) return null
      if (result.runId !== runId || (version != null && result.plan?.planVersion !== version)) {
        throw new Error('规划版本不匹配')
      }
      cache.set(key, result.plan)
      return result.plan
    }
    try {
      const [selected, before] = await Promise.all([
        read(input.planVersion.value),
        input.comparing.value && input.previousVersion.value != null ? read(input.previousVersion.value) : null,
      ])
      if (local.signal.aborted || current !== request) return
      plan.value = selected
      previous.value = before
    } catch {
      if (local.signal.aborted || current !== request) return
      error.value = 'ACG 规划快照读取失败，请重试。'
    } finally {
      if (current === request) loading.value = false
    }
  }
  watch(() => [input.runId.value, input.planVersion.value, input.previousVersion.value,
    input.identity.value, input.enabled.value, input.historical.value, input.comparing.value], () => { void refresh() }, { immediate: true })
  onScopeDispose(() => { request++; controller?.abort(); cache.clear() })
  const difference = computed(() => input.comparing.value && previous.value && plan.value
    ? compareGraphs(planningGraph(previous.value), planningGraph(plan.value)) : null)
  return { plan, previous, difference, loading, error, refresh }
}
