import { computed, onScopeDispose, ref, shallowRef, watch, type InjectionKey, type Ref } from 'vue'
import { agentosApi, type GraphProjection, type GraphVersionEntry, type GraphVersionHistory } from '@/services/api/agentos'
import type { GraphDifference } from '@/utils/acgGraphDifference'
export type { GraphDifference } from '@/utils/acgGraphDifference'

export const graphVersionKey = (entry: GraphVersionEntry) => entry.blueprintId || `${entry.graphId}:v${entry.graphVersion}`
export const graphVersionTime = (entry: GraphVersionEntry) => {
  const value = entry.activatedAt || entry.createdAt
  if (!value) return '时间未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未记录' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// Compare structure only. Runtime activation/status facts are deliberately excluded.
const nodeContent = (node: GraphProjection['nodes'][number]) => JSON.stringify([
  node.nodeType, node.name, node.description, node.goal, node.agentName, node.capability, node.controlType,
  node.display?.semanticTaskKey, node.display?.logicalRole, node.display?.dependencyKeys, node.display?.allowedSkills
])
const edgeContent = (edge: GraphProjection['edges'][number]) => JSON.stringify([edge.sourceId, edge.targetId, edge.edgeType, edge.condition])
export const compareGraphs = (before: GraphProjection, after: GraphProjection): GraphDifference => {
  const compare = <T>(left: T[], right: T[], key: (value: T) => string, content: (value: T) => string) => {
    const previous = new Map(left.map(value => [key(value), content(value)]))
    const next = new Map(right.map(value => [key(value), content(value)]))
    return {
      added: [...next.keys()].filter(id => !previous.has(id)),
      updated: [...next.keys()].filter(id => previous.has(id) && previous.get(id) !== next.get(id)),
      removed: [...previous.keys()].filter(id => !next.has(id))
    }
  }
  const nodes = compare(before.nodes, after.nodes, node => node.nodeId, nodeContent)
  const edges = compare(before.edges, after.edges, edge => edge.edgeId, edgeContent)
  return { addedNodeIds: nodes.added, updatedNodeIds: nodes.updated, removedNodeIds: nodes.removed,
    addedEdgeIds: edges.added, updatedEdgeIds: edges.updated, removedEdgeIds: edges.removed }
}

type GraphVersionsApi = Pick<typeof agentosApi, 'getGraphVersions' | 'getGraphSnapshot'>

/** One workspace-owned browser state shared by Explorer and the graph editor. */
export const createGraphVersions = (
  runId: Readonly<Ref<string | null>>,
  liveGraph: Readonly<Ref<GraphProjection | null>>,
  watermark: Readonly<Ref<unknown>>,
  api: GraphVersionsApi = agentosApi
) => {
  const history = shallowRef<GraphVersionHistory | null>(null)
  const following = ref(true)
  const pinnedKey = ref<string | null>(null)
  const comparing = ref(false)
  const loading = ref(false)
  const snapshotPending = ref(false)
  const error = ref('')
  const snapshotFailures = shallowRef<Record<string, boolean>>({})
  const snapshots = shallowRef<Record<string, GraphProjection>>({})
  let generation = 0
  let listRequest = 0
  let snapshotRequest = 0
  let controller: AbortController | null = null
  const entries = computed(() => [...(history.value?.items || [])].sort((a, b) => a.graphVersion - b.graphVersion))
  const current = computed(() => entries.value.find(entry => entry.current) || null)
  const selected = computed(() => following.value ? current.value : entries.value.find(entry => graphVersionKey(entry) === pinnedKey.value) || null)
  const selectedKey = computed(() => selected.value ? graphVersionKey(selected.value) : null)
  const historical = computed(() => Boolean(selected.value && !selected.value.current))
  const previous = computed(() => {
    const index = entries.value.findIndex(entry => graphVersionKey(entry) === selectedKey.value)
    return index > 0 ? entries.value[index - 1] : null
  })
  const cached = (entry: GraphVersionEntry | null) => entry ? snapshots.value[graphVersionKey(entry)] || null : null
  const available = (entry: GraphVersionEntry) => entry.current && liveGraph.value?.graphId === entry.graphId
    && liveGraph.value.graphVersion === entry.graphVersion ? liveGraph.value : cached(entry)
  const displayGraph = computed(() => {
    if (!selected.value) return following.value ? liveGraph.value : null
    return available(selected.value)
  })
  const previousGraph = computed(() => cached(previous.value))
  const difference = computed(() => comparing.value && previousGraph.value && displayGraph.value
    ? compareGraphs(previousGraph.value, displayGraph.value) : null)
  const required = computed(() => selected.value
    ? [selected.value, ...(comparing.value && previous.value ? [previous.value] : [])] : [])
  const selectionIdentity = computed(() => JSON.stringify(required.value.map(entry => [graphVersionKey(entry), entry.current])))
  const liveSelectionKey = computed(() => selected.value?.current && liveGraph.value && available(selected.value) === liveGraph.value
    ? selectedKey.value : null)
  const snapshotLoading = computed(() => snapshotPending.value && required.value.some(entry => !available(entry)))
  const snapshotError = computed(() => required.value.some(entry => !available(entry) && snapshotFailures.value[graphVersionKey(entry)])
    ? '图快照加载失败，请重试' : '')

  const ensureSnapshot = async (entry: GraphVersionEntry, expectedRun: string, signal: AbortSignal, isCurrent: () => boolean) => {
    const key = graphVersionKey(entry)
    if (available(entry)) return
    const graph = await api.getGraphSnapshot(expectedRun, entry.blueprintId, { signal })
    if (!isCurrent()) return
    // A current graph can advance during the request. Never cache it under an older version.
    if (graph.graphId !== entry.graphId || graph.graphVersion !== entry.graphVersion) throw new Error('图版本已更新，请刷新版本列表')
    const { workspaceReview: _currentReview, ...snapshot } = graph
    snapshots.value = { ...snapshots.value, [key]: snapshot }
  }
  const loadSelection = async () => {
    controller?.abort()
    controller = new AbortController()
    const signal = controller.signal
    const expectedGeneration = generation
    const request = ++snapshotRequest
    const expectedRun = runId.value
    const expectedSelection = selectionIdentity.value
    const entries = required.value
    const isCurrent = () => !signal.aborted && expectedGeneration === generation && request === snapshotRequest
      && runId.value === expectedRun && selectionIdentity.value === expectedSelection
    const failures = { ...snapshotFailures.value }
    for (const entry of entries) delete failures[graphVersionKey(entry)]
    snapshotFailures.value = failures
    if (!entries.length || !expectedRun) { snapshotPending.value = false; return }
    snapshotPending.value = true
    try {
      await Promise.all(entries.map(async entry => {
        try {
          await ensureSnapshot(entry, expectedRun, signal, isCurrent)
        } catch {
          if (isCurrent() && !available(entry)) snapshotFailures.value = { ...snapshotFailures.value, [graphVersionKey(entry)]: true }
        }
      }))
    } finally {
      if (isCurrent()) snapshotPending.value = false
    }
  }
  const refresh = async () => {
    if (!runId.value) return
    const expectedRun = runId.value
    const request = ++listRequest
    loading.value = true
    try {
      const result = await api.getGraphVersions(expectedRun)
      if (request !== listRequest || runId.value !== expectedRun) return
      if (result.runId !== expectedRun) throw new Error('Run mismatch')
      const pinned = !following.value ? selected.value : null
      history.value = result
      // Identity promotion can give an activated current version its blueprint ID later.
      if (pinned) {
        const promoted = result.items.find(entry => entry.graphId === pinned.graphId && entry.graphVersion === pinned.graphVersion)
        if (promoted) pinnedKey.value = graphVersionKey(promoted)
      }
      error.value = ''
    } catch {
      if (request === listRequest && runId.value === expectedRun) error.value = '版本记录暂时不可用'
    } finally {
      if (request === listRequest) loading.value = false
    }
  }
  const select = (key: string) => {
    if (!entries.value.some(entry => graphVersionKey(entry) === key)) return
    following.value = false
    pinnedKey.value = key
  }
  const follow = () => { following.value = true; pinnedKey.value = null }
  watch(runId, () => {
    generation++
    listRequest++
    snapshotRequest++
    controller?.abort()
    history.value = null
    snapshots.value = {}
    following.value = true
    pinnedKey.value = null
    comparing.value = false
    loading.value = false
    snapshotPending.value = false
    error.value = ''
    snapshotFailures.value = {}
    void refresh()
  }, { immediate: true, flush: 'sync' })
  watch(watermark, () => { void refresh() })
  watch([selectionIdentity, liveSelectionKey], () => { void loadSelection() })
  onScopeDispose(() => { generation++; listRequest++; snapshotRequest++; controller?.abort() })
  return { history, entries, current, selected, selectedKey, previous, following, historical, comparing,
    loading, snapshotLoading, error, snapshotError, displayGraph, previousGraph, difference,
    select, follow, refresh, retrySnapshot: loadSelection }
}

export type GraphVersionsController = ReturnType<typeof createGraphVersions>
export const graphVersionsKey: InjectionKey<GraphVersionsController> = Symbol('workspace-graph-versions')
