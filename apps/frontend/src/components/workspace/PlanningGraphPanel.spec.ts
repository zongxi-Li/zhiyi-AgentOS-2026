import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlanningGraphPanel from './PlanningGraphPanel.vue'
import { graphVersionsKey, type GraphVersionsController } from './graphVersions'
import { agentosApi, type GraphProjection, type GraphVersionEntry } from '@/services/api/agentos'

const current: GraphVersionEntry = {
  blueprintId: 'current', graphId: 'graph', graphVersion: 3, taskPlanVersion: 3, current: true,
  status: 'active', createdAt: null, predecessorBlueprintId: null, reason: null, patch: null,
  inherited: { completedStepIds: [], skippedStepIds: [], attemptIds: [], outputRefs: {} },
}
const graph: GraphProjection = { graphId: 'graph', graphVersion: 3, taskPlanVersion: 3, nodes: [], edges: [] }
const setup = (initial: GraphVersionEntry | null = current, following = true) => {
  const versions = {
    historical: ref(Boolean(initial && !initial.current)),
    following: ref(following),
    selected: ref<GraphVersionEntry | null>(initial),
    selectedKey: ref(initial?.blueprintId || null),
    previous: ref(null),
    comparing: ref(false),
  }
  const wrapper = mount(PlanningGraphPanel, {
    props: { runId: 'run', graph, graphNodes: [], initialPlanVersion: 1 },
    global: {
      provide: { [graphVersionsKey as symbol]: versions as unknown as GraphVersionsController },
      stubs: { PlanningGraphView: { props: ['plan'], template: '<div class="plan-probe">{{ plan?.planVersion }}</div>' } },
    },
  })
  return { versions, wrapper }
}

beforeEach(() => {
  vi.spyOn(agentosApi, 'getPlanSnapshot').mockImplementation(async (runId, version) => ({
    runId, plan: { planVersion: version || 3, commitId: null, commitmentRevision: null,
      objective: '审查仓库', tasks: [], constraints: [], expectedArtifacts: [], relations: [] },
  }))
})
afterEach(() => vi.restoreAllMocks())

describe('PlanningGraphPanel version boundaries', () => {
  it('clears the current planning snapshot if the pinned RGraph entry is no longer available', async () => {
    const { wrapper, versions } = setup()
    await flushPromises()
    expect(wrapper.get('.plan-probe').text()).toBe('3')
    versions.following.value = false
    versions.selected.value = null
    versions.selectedKey.value = null
    await flushPromises()
    expect(wrapper.find('.plan-probe').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('没有登记对应的 ACG 版本')
    expect(agentosApi.getPlanSnapshot).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does not borrow the current graph or initial consent plan version for a historical RGraph with no ACG version', async () => {
    const { wrapper } = setup({ ...current, blueprintId: 'history', graphVersion: 1, taskPlanVersion: null,
      current: false, status: 'historical' }, false)
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('没有登记对应的 ACG 版本')
    expect(wrapper.find('.plan-probe').exists()).toBe(false)
    expect(agentosApi.getPlanSnapshot).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
