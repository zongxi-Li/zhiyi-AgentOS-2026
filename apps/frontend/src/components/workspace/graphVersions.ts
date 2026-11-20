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
  const snapshotLoading = ref(false)
  const error = ref('')
  const snapshotError = ref('')
  const snapshots = shallowRef<Record<string, GraphProjection>>({})
  let generation = 0
  let listRequest = 0
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
  const displayGraph = computed(() => {
    if (!selected.value) return following.value ? liveGraph.value : null
    if (selected.value.current && liveGraph.value?.graphId === selected.value.graphId
      && liveGraph.value.graphVersion === selected.value.graphVersion) return liveGraph.value
    return cached(selected.value)
  })
  const previousGraph = computed(() => cached(previous.value))
  const difference = computed(() => comparing.value && previousGraph.value && displayGraph.value
    ? compareGraphs(previousGraph.value, displayGraph.value) : null)

  const ensureSnapshot = async (entry: GraphVersionEntry, signal: AbortSignal, expectedGeneration: number) => {
    const key = graphVersionKey(entry)
    if (snapshots.value[key]) return
    const graph = await api.getGraphSnapshot(runId.value!, entry.blueprintId, { signal })
    if (signal.aborted || generation !== expectedGeneration) return
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
    snapshotError.value = ''
    const entry = selected.value
    if (!entry || !runId.value) { snapshotLoading.value = false; return }
    snapshotLoading.value = true
    try {
      const requests = [ensureSnapshot(entry, signal, expectedGeneration)]
      if (comparing.value && previous.value) requests.push(ensureSnapshot(previous.value, signal, expectedGeneration))
      await Promise.all(requests)
    } catch {
      if (!signal.aborted && expectedGeneration === generation) snapshotError.value = '图快照加载失败，请重试'
    } finally {
      if (!signal.aborted && expectedGeneration === generation) snapshotLoading.value = false
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
    controller?.abort()
    history.value = null
    snapshots.value = {}
    following.value = true
    pinnedKey.value = null
    comparing.value = false
    loading.value = false
    snapshotLoading.value = false
    error.value = ''
    snapshotError.value = ''
    void refresh()
  }, { immediate: true, flush: 'sync' })
  watch(watermark, () => { void refresh() })
  watch([selectedKey, comparing, () => previous.value && graphVersionKey(previous.value)], () => { void loadSelection() })
  onScopeDispose(() => { generation++; listRequest++; controller?.abort() })
  return { history, entries, current, selected, selectedKey, previous, following, historical, comparing,
    loading, snapshotLoading, error, snapshotError, displayGraph, previousGraph, difference,
    select, follow, refresh, retrySnapshot: loadSelection }
}

export type GraphVersionsController = ReturnType<typeof createGraphVersions>
export const graphVersionsKey: InjectionKey<GraphVersionsController> = Symbol('workspace-graph-versions')
