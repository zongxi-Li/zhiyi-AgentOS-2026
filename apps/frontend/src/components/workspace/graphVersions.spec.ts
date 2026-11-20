import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { compareGraphs, createGraphVersions } from './graphVersions'
import type { GraphProjection, GraphVersionEntry, GraphVersionHistory } from '@/services/api/agentos'

const graph = (version: number): GraphProjection => ({ graphId: 'g', graphVersion: version,
  nodes: [{ nodeId: 'a', nodeType: 'step', name: version === 1 ? '读取' : '审查' },
    ...(version > 1 ? [{ nodeId: 'b', nodeType: 'step' as const, name: '补读' }] : [])], edges: [] })
const entry = (version: number, current = false): GraphVersionEntry => ({ blueprintId: `bp${version}`, graphId: 'g', graphVersion: version,
  current, status: current ? 'active' : 'historical', createdAt: null, predecessorBlueprintId: version > 1 ? `bp${version - 1}` : null,
  reason: null, patch: null, inherited: { completedStepIds: [], skippedStepIds: [], attemptIds: [], outputRefs: {} } })
const history = (version: number, runId = 'r'): GraphVersionHistory => ({ runId, graphId: 'g', currentBlueprintId: `bp${version}`,
  currentGraphVersion: version, items: Array.from({ length: version }, (_, index) => entry(index + 1, index + 1 === version)) })
const settle = async () => { for (let index = 0; index < 8; index++) await nextTick() }
const setup = () => {
  const runId = ref<string | null>('r')
  const live = ref<GraphProjection | null>(graph(2))
  const watermark = ref(1)
  const api = { getGraphVersions: vi.fn().mockResolvedValue(history(2)),
    getGraphSnapshot: vi.fn(async (_run: string, id: string | null) => graph(Number(id?.replace('bp', '') || 2))) }
  const scope = effectScope()
  const state = scope.run(() => createGraphVersions(runId, live, watermark, api))!
  return { scope, state, api, runId, live, watermark }
}

describe('workspace graph versions', () => {
  it('keeps an activated version selected when its Identity blueprint is promoted', async () => {
    const { scope, state, api } = setup()
    await settle()
    const activated = history(2)
    activated.currentBlueprintId = null
    activated.items[1].blueprintId = null
    api.getGraphVersions.mockResolvedValue(activated)
    await state.refresh()
    state.select('g:v2')
    await settle()
    api.getGraphVersions.mockResolvedValue(history(2))
    await state.refresh()
    await settle()
    expect(state.selectedKey.value).toBe('bp2')
    expect(state.selected.value?.graphVersion).toBe(2)
    expect(state.following.value).toBe(false)
    scope.stop()
  })
  it('follows accepted versions until the user pins a snapshot, and resumes following explicitly', async () => {
    const { scope, state, api, live } = setup()
    await settle()
    expect(state.selected.value?.graphVersion).toBe(2)
    state.select('bp1')
    await settle()
    expect(state.displayGraph.value?.graphVersion).toBe(1)
    api.getGraphVersions.mockResolvedValue(history(3))
    live.value = graph(3)
    await state.refresh()
    await settle()
    expect(state.selected.value?.graphVersion).toBe(1)
    expect(state.historical.value).toBe(true)
    state.follow()
    await settle()
    expect(state.selected.value?.graphVersion).toBe(3)
    expect(state.displayGraph.value?.graphVersion).toBe(3)
    scope.stop()
  })

  it('compares adjacent immutable snapshots and keeps live execution facts out of structure differences', async () => {
    const { scope, state } = setup()
    await settle()
    state.comparing.value = true
    await settle()
    expect(state.difference.value?.addedNodeIds).toEqual(['b'])
    expect(state.difference.value?.updatedNodeIds).toEqual(['a'])
    const old = { ...graph(1), edges: [{ edgeId: 'e', sourceId: 'a', targetId: 'b', edgeType: 'dependency' as const, activation: 'inactive' as const }] }
    expect(compareGraphs(old, { ...old, edges: [{ ...old.edges[0], activation: 'active' }] }).updatedEdgeIds).toEqual([])
    scope.stop()
  })

  it('ignores delayed responses from a previously selected Run and resets pinned state', async () => {
    const { scope, state, api, runId } = setup()
    await settle()
    state.select('bp1')
    let resolveOld!: (value: GraphVersionHistory) => void
    api.getGraphVersions.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    const pending = state.refresh()
    api.getGraphVersions.mockResolvedValue(history(1, 'other'))
    runId.value = 'other'
    await settle()
    resolveOld(history(3))
    await pending
    expect(state.history.value?.runId).toBe('other')
    expect(state.following.value).toBe(true)
    expect(state.comparing.value).toBe(false)
    scope.stop()
  })

  it('retains the selected snapshot when the version list refresh fails', async () => {
    const { scope, state, api } = setup()
    await settle()
    state.select('bp1')
    await settle()
    api.getGraphVersions.mockRejectedValue(new Error('offline'))
    await state.refresh()
    expect(state.error.value).toBeTruthy()
    expect(state.displayGraph.value?.graphVersion).toBe(1)
    scope.stop()
  })
})
