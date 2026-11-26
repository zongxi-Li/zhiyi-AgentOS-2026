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
const setup = (initialLive: GraphProjection | null = graph(2)) => {
  const runId = ref<string | null>('r')
  const live = ref<GraphProjection | null>(initialLive)
  const watermark = ref(1)
  const api = { getGraphVersions: vi.fn().mockResolvedValue(history(2)),
    getGraphSnapshot: vi.fn(async (_run: string, id: string | null) => graph(Number(id?.replace('bp', '') || 2))) }
  const scope = effectScope()
  const state = scope.run(() => createGraphVersions(runId, live, watermark, api))!
  return { scope, state, api, runId, live, watermark }
}

describe('workspace graph versions', () => {
  it('shares concurrent history refreshes and coalesces version invalidations into one follow-up', async () => {
    const { scope, state, api, watermark } = setup()
    await settle()
    let finish!: (value: GraphVersionHistory) => void
    api.getGraphVersions.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const first = state.refresh()
    const second = state.refresh()
    expect(first).toBe(second)
    watermark.value = 2
    await settle()
    watermark.value = 3
    await settle()
    expect(api.getGraphVersions).toHaveBeenCalledTimes(2)
    finish(history(2))
    await first
    await settle()
    expect(api.getGraphVersions).toHaveBeenCalledTimes(3)
    expect(state.loading.value).toBe(false)
    scope.stop()
  })
  it('uses the matching live graph without requesting a redundant current snapshot', async () => {
    const { scope, state, api } = setup()
    await settle()
    expect(state.displayGraph.value?.graphVersion).toBe(2)
    expect(state.snapshotError.value).toBe('')
    expect(state.snapshotLoading.value).toBe(false)
    expect(api.getGraphSnapshot).not.toHaveBeenCalled()
    scope.stop()
  })

  it.each(['before', 'after'])('clears an obsolete snapshot failure when live data recovers %s the request fails', async timing => {
    const { scope, state, api, live } = setup(null)
    let rejectSnapshot!: (error: Error) => void
    api.getGraphSnapshot.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectSnapshot = reject }))
    await settle()
    expect(state.snapshotLoading.value).toBe(true)
    if (timing === 'after') {
      rejectSnapshot(new Error('offline'))
      await settle()
      expect(state.snapshotError.value).toBeTruthy()
    }
    live.value = graph(2)
    await settle()
    if (timing === 'before') rejectSnapshot(new Error('late failure'))
    await settle()
    expect(state.displayGraph.value?.graphVersion).toBe(2)
    expect(state.snapshotError.value).toBe('')
    expect(state.snapshotLoading.value).toBe(false)
    scope.stop()
  })

  it('retains a failed comparison snapshot when the current live graph recovers', async () => {
    const { scope, state, api, live } = setup(null)
    api.getGraphSnapshot.mockRejectedValue(new Error('offline'))
    state.comparing.value = true
    await settle()
    expect(state.snapshotError.value).toBeTruthy()
    live.value = graph(2)
    await settle()
    expect(state.displayGraph.value?.graphVersion).toBe(2)
    expect(state.snapshotError.value).toBeTruthy()
    expect(state.difference.value).toBeNull()
    api.getGraphSnapshot.mockImplementation(async (_run, id) => graph(Number(id?.replace('bp', ''))))
    await state.retrySnapshot()
    expect(state.snapshotError.value).toBe('')
    expect(state.difference.value?.addedNodeIds).toEqual(['b'])
    scope.stop()
  })

  it('ignores an old selection failure even before its abort watcher runs', async () => {
    const { scope, state, api } = setup()
    await settle()
    let rejectSnapshot!: (error: Error) => void
    api.getGraphSnapshot.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectSnapshot = reject }))
    state.select('bp1')
    await settle()
    state.follow()
    rejectSnapshot(new Error('obsolete selection'))
    await settle()
    expect(state.displayGraph.value?.graphVersion).toBe(2)
    expect(state.snapshotError.value).toBe('')
    expect(state.snapshotLoading.value).toBe(false)
    scope.stop()
  })

  it('ignores a late failure from a superseded retry of the same version', async () => {
    const { scope, state, api } = setup(null)
    let rejectSnapshot!: (error: Error) => void
    api.getGraphSnapshot.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectSnapshot = reject }))
    await settle()
    await state.retrySnapshot()
    expect(state.displayGraph.value?.graphVersion).toBe(2)
    rejectSnapshot(new Error('obsolete request'))
    await settle()
    expect(state.snapshotError.value).toBe('')
    expect(state.snapshotLoading.value).toBe(false)
    scope.stop()
  })

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
