<template>
  <section class="run-progress" aria-label="运行进度文档">
    <div class="run-progress__document-head">
      <RunBreadcrumb :mission-title="missionTitle" :items="breadcrumbItems" @locate="locateBreadcrumb" />
      <header class="run-progress__header">
        <div class="run-progress__eyebrow">RUN DOCUMENT</div>
        <div class="run-progress__heading-row">
          <div class="run-progress__heading-copy">
            <h1 class="run-progress__goal">{{ goalTitle }}</h1>
            <p class="run-progress__summary">{{ goalSummary }}</p>
          </div>
          <button type="button" class="run-progress__mission-link" @click="openMission">查看 mission.md</button>
        </div>
        <div class="run-progress__meta">
          <span class="run-progress__status" :class="'is-' + runState">{{ stateLabel }}</span>
          <span v-if="durationText" class="run-progress__duration">{{ durationText }}</span>
          <span v-if="resolvedRunId" class="run-progress__runid">{{ resolvedRunId }}</span>
        </div>
      </header>
    </div>

    <div v-if="!resolvedRunId" class="run-progress__empty">运行开始后，这里会显示任务规划和执行过程。</div>

    <template v-else>
      <div class="run-progress__toolbar">
        <span class="run-progress__toolbar-label">OUTLINE</span>
        <label class="run-progress__filter">
          <span>Filter</span>
          <input v-model="filterText" type="search" placeholder="symbols" aria-label="过滤 Run symbols" />
        </label>
      </div>

      <div ref="scrollBody" class="run-progress__body" @scroll="onScroll">
        <div class="run-progress__stream">
          <div v-if="visibleSymbols.length" class="run-progress__browser" aria-label="Run document columns">
            <section v-for="column in browserColumns" :key="column.id" class="run-progress__column">
              <div class="run-progress__column-head">{{ column.title }}</div>
              <div v-if="column.detail" class="run-progress__detail">
                <div class="run-progress__detail-status">
                  <span class="run-progress__detail-mark" :class="`is-${column.detail.status}`">{{ detailStatusMark(column.detail.status) }}</span>
                  <strong>{{ column.detail.title }}</strong>
                </div>
                <p v-if="column.detail.subtitle" class="run-progress__detail-summary">{{ column.detail.subtitle }}</p>
                <dl v-if="detailRows(column.detail).length" class="run-progress__detail-list">
                  <div v-for="row in detailRows(column.detail)" :key="row.label">
                    <dt>{{ row.label }}</dt>
                    <dd>{{ row.value }}</dd>
                  </div>
                </dl>
                <pre v-if="column.detail.content" class="run-progress__detail-content">{{ column.detail.content }}</pre>
              </div>
              <div v-else class="run-progress__column-body">
                <RunSymbolRow
                  v-for="item in column.symbols"
                  :key="item.id"
                  :symbol="item"
                  :selected-symbol-id="selectedSymbolIdForView"
                  :is-expanded="isBrowserExpanded"
                  horizontal
                  @toggle="toggleBrowser"
                  @select="selectSymbol"
                  @open="openSymbol"
                />
              </div>
            </section>
          </div>
          <p v-if="!visibleSymbols.length" class="run-progress__waiting">
            {{ filterText ? '没有匹配的 Symbol。' : runState === 'running' ? '等待 Runtime Projection…' : '该 Run 暂无可展示的 Runtime facts。' }}
          </p>
        </div>

        <button v-if="!followLatest" type="button" class="run-progress__follow" @click="scrollToLatest">↘ 跟随最新运行</button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { MissionWorkspaceProjection, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'
import RunBreadcrumb from './RunBreadcrumb.vue'
import RunSymbolRow from './RunSymbolRow.vue'
import { findRunDocumentSymbol, projectRunDocument, type RunDocumentSymbol } from '@/workbench/runtime/runDocument'

const props = defineProps<{
  entry: WorkspaceEntry
  projection: MissionWorkspaceProjection
  graphNodes: WorkspaceGraphNode[]
  runId: string | null
  selectedSemanticTaskKey?: string | null
  selectedSymbolId?: string | null
  runtimeObservation: RuntimeObservation | null
  runtimeStore?: RuntimeEventStore | null
}>()

const emit = defineEmits<{
  selectSemanticTask: [semanticTaskKey: string | null]
  selectSymbol: [symbol: RunDocumentSymbol]
  locateGraph: [entry: WorkspaceEntry]
  openArtifact: [entry: WorkspaceEntry]
  openEntry: [entry: WorkspaceEntry]
  openSemanticTask: [semanticTaskKey: string | null]
}>()

const resolvedRunId = computed(() => props.runId || (props.entry.kind === 'run' ? props.entry.runId || null : null))
const observedRun = computed(() => props.projection.runs.find(item => item.runId === resolvedRunId.value) || null)
const runStatus = computed(() => (
  props.runtimeObservation?.runId === resolvedRunId.value
    ? props.runtimeObservation.runStatus
    : observedRun.value?.status || props.runtimeObservation?.runStatus || null
))

const TERMINAL_OK = new Set(['completed', 'succeeded'])
const TERMINAL_BAD = new Set(['failed', 'cancelled'])
const runState = computed<'idle' | 'unknown' | 'running' | 'completed' | 'failed' | 'paused'>(() => {
  if (!resolvedRunId.value) return 'idle'
  const status = runStatus.value
  if (!status) return 'unknown'
  if (TERMINAL_OK.has(status)) return 'completed'
  if (TERMINAL_BAD.has(status)) return 'failed'
  if (status === 'waiting_review') return 'paused'
  if (['queued', 'starting', 'running', 'executing', 'planning', 'pending', 'retrying'].includes(status)) return 'running'
  return 'unknown'
})

const STATE_LABELS: Record<string, string> = {
  idle: '尚未运行',
  running: 'RUNNING',
  completed: '运行完成',
  failed: '运行失败',
  paused: '等待审核',
  unknown: '状态未知'
}
const stateLabel = computed(() => {
  const planningStatus = props.runtimeStore?.planning.status
  return planningStatus && ['STARTING', 'RUNNING'].includes(planningStatus)
    ? 'PLANNING'
    : (STATE_LABELS[runState.value] || '状态未知')
})

const shorten = (value: string, length: number) => value.length > length ? `${value.slice(0, length)}…` : value
const goalSource = computed(() => props.projection.mission.goal || props.projection.mission.description || '运行进度')
const goalTitle = computed(() => {
  const firstLine = goalSource.value.split(/[\n。！？!?]/)[0].trim()
  return shorten(firstLine || '运行进度', 58)
})
const goalSummary = computed(() => {
  const description = props.projection.mission.description?.trim()
  if (description && description !== goalSource.value) return shorten(description, 180)
  return shorten(goalSource.value, 180)
})
const missionTitle = computed(() => shorten(goalTitle.value, 32))

const nowTick = ref(0)
let durationTimer: ReturnType<typeof setInterval> | null = null
watch(runState, state => {
  if (state === 'running' && durationTimer === null) durationTimer = setInterval(() => { nowTick.value += 1 }, 1000)
  else if (state !== 'running' && durationTimer !== null) {
    clearInterval(durationTimer)
    durationTimer = null
  }
}, { immediate: true })
onBeforeUnmount(() => { if (durationTimer !== null) clearInterval(durationTimer) })

const formatDuration = (ms: number) => {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes) return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  const precise = ms / 1000
  return `${Number(precise.toFixed(1))}s`
}
const durationText = computed(() => {
  void nowTick.value
  const liveElapsed = props.runtimeStore?.planning.elapsedMs
  const planningStatus = props.runtimeStore?.planning.status
  if (planningStatus && ['STARTING', 'RUNNING'].includes(planningStatus) && liveElapsed != null) return formatDuration(liveElapsed)
  const start = observedRun.value?.createdAt
  if (!start) return null
  const startedAt = new Date(start).getTime()
  if (Number.isNaN(startedAt)) return null
  const finishedAt = observedRun.value?.completedAt
  const end = finishedAt && !Number.isNaN(new Date(finishedAt).getTime()) ? new Date(finishedAt).getTime() : Date.now()
  return formatDuration(end - startedAt)
})

const documentModel = computed(() => projectRunDocument({
  runId: resolvedRunId.value,
  mission: props.projection.mission,
  graph: props.projection.activeGraph,
  graphNodes: props.graphNodes,
  entries: props.projection.entries,
  runtimeObservation: props.runtimeObservation,
  runtimeStore: props.runtimeStore
}))

const expandedSymbols = ref(new Map<string, boolean>())
const defaultExpanded = (symbol: RunDocumentSymbol) => symbol.defaultExpanded ?? ['running', 'warning', 'failed'].includes(symbol.status)
const isExpanded = (symbol: RunDocumentSymbol) => expandedSymbols.value.get(symbol.id) ?? defaultExpanded(symbol)
const toggleExpanded = (symbol: RunDocumentSymbol) => {
  const next = new Map(expandedSymbols.value)
  next.set(symbol.id, !isExpanded(symbol))
  expandedSymbols.value = next
}

const filterText = ref('')
const symbolMatches = (symbol: RunDocumentSymbol, needle: string) => [symbol.title, symbol.subtitle, symbol.type, symbol.semanticTaskKey, symbol.graphNodeId, symbol.artifactKey]
  .filter(Boolean)
  .some(value => String(value).toLowerCase().includes(needle))
const filterTree = (symbols: RunDocumentSymbol[], needle: string): RunDocumentSymbol[] => {
  if (!needle) return symbols
  return symbols.reduce<RunDocumentSymbol[]>((result, item) => {
    const children = filterTree(item.children, needle)
    if (symbolMatches(item, needle) || children.length) result.push({ ...item, children })
    return result
  }, [])
}
const visibleSymbols = computed(() => filterTree(documentModel.value.symbols, filterText.value.trim().toLowerCase()))

const horizontalPath = ref<string[]>([])
const activeSymbolId = ref<string | null>(props.selectedSymbolId || null)
const selectedSymbolIdForView = computed(() => props.selectedSymbolId || activeSymbolId.value)
const detailStatusMark = (status: RunDocumentSymbol['status']) => ({
  running: '●',
  completed: '✓',
  warning: '!',
  failed: '×',
  pending: '○'
}[status])
const detailRows = (symbol: RunDocumentSymbol) => {
  const rows: Array<{ label: string; value: string | number }> = [
    { label: 'Type', value: symbol.type },
    ...(symbol.semanticTaskKey ? [{ label: 'semanticTaskKey', value: symbol.semanticTaskKey }] : []),
    ...(symbol.graphNodeId ? [{ label: 'ACG Node', value: symbol.graphNodeId }] : []),
    ...(symbol.artifactKey ? [{ label: 'artifactKey', value: symbol.artifactKey }] : []),
    ...(symbol.artifactId ? [{ label: 'artifactId', value: symbol.artifactId }] : [])
  ]
  for (const [key, value] of Object.entries(symbol.metrics || {})) {
    rows.push({ label: key, value: key === 'Duration' && typeof value === 'number' ? `${value} ms` : value })
  }
  return rows
}
const browserColumns = computed(() => {
  const columns: Array<{ id: string; title: string; symbols: RunDocumentSymbol[]; detail?: RunDocumentSymbol }> = [{
    id: 'root',
    title: 'OUTLINE',
    symbols: visibleSymbols.value
  }]
  let currentSymbols = visibleSymbols.value
  for (const selectedId of horizontalPath.value) {
    const selected = currentSymbols.find(item => item.id === selectedId)
    if (!selected || !selected.children.length) break
    columns.push({ id: selected.id, title: selected.title, symbols: selected.children })
    currentSymbols = selected.children
  }
  const selected = findRunDocumentSymbol(documentModel.value.symbols, selectedSymbolIdForView.value)
  const selectedIsVisible = selected && columns.some(column => column.symbols.some(item => item.id === selected.id))
  if (selected && selectedIsVisible && !selected.children.length) {
    columns.push({ id: `detail:${selected.id}`, title: 'INSPECTOR', symbols: [], detail: selected })
  }
  return columns
})
const isBrowserExpanded = (symbol: RunDocumentSymbol) => horizontalPath.value.includes(symbol.id)
const toggleBrowser = (symbol: RunDocumentSymbol) => {
  const columnIndex = browserColumns.value.findIndex(column => column.symbols.some(item => item.id === symbol.id))
  if (columnIndex < 0 || !symbol.children.length) return
  const prefix = horizontalPath.value.slice(0, columnIndex)
  const isOpen = horizontalPath.value[columnIndex] === symbol.id
  horizontalPath.value = isOpen ? prefix : [...prefix, symbol.id]
}
const parentPathFor = (symbols: RunDocumentSymbol[], targetId: string, parents: string[] = []): string[] | null => {
  for (const item of symbols) {
    if (item.id === targetId) return parents
    const nested = parentPathFor(item.children, targetId, [...parents, item.id])
    if (nested) return nested
  }
  return null
}
const defaultPathFor = (symbols: RunDocumentSymbol[]) => {
  const path: string[] = []
  let current = symbols
  while (true) {
    const next = current.find(item => item.defaultExpanded && item.children.length)
    if (!next) return path
    path.push(next.id)
    current = next.children
  }
}

const firstRunningTask = (symbols: RunDocumentSymbol[]): RunDocumentSymbol | null => {
  for (const item of symbols) {
    if (item.type === 'task' && item.status === 'running') return item
    const nested = firstRunningTask(item.children)
    if (nested) return nested
  }
  return null
}
watch(documentModel, model => {
  // The runtime may expose the current task before the user has selected a
  // symbol. Following that real active node keeps the Inspector useful while
  // leaving completed/pending Runs unselected.
  if (props.selectedSymbolId || props.selectedSemanticTaskKey) return
  const current = firstRunningTask(model.symbols)
  if (current) {
    const currentPath = parentPathFor(model.symbols, current.id)
    horizontalPath.value = currentPath
      ? current.children.length ? [...currentPath, current.id] : currentPath
      : horizontalPath.value
    emit('selectSymbol', current)
    emit('selectSemanticTask', current.semanticTaskKey || null)
  } else if (!horizontalPath.value.length) {
    horizontalPath.value = defaultPathFor(model.symbols)
  }
}, { immediate: true })
watch(() => props.selectedSymbolId, selectedId => {
  activeSymbolId.value = selectedId || null
  if (!selectedId) return
  const path = parentPathFor(documentModel.value.symbols, selectedId)
  if (path) horizontalPath.value = path
}, { immediate: true })

const breadcrumbItems = computed(() => {
  const selected = findRunDocumentSymbol(documentModel.value.symbols, props.selectedSymbolId || null)
  if (!selected) return []
  const path: RunDocumentSymbol[] = []
  const visit = (items: RunDocumentSymbol[]): boolean => {
    for (const item of items) {
      if (item.id === selected.id) { path.push(item); return true }
      if (visit(item.children)) { path.unshift(item); return true }
    }
    return false
  }
  visit(documentModel.value.symbols)
  return path
})

const symbolEntry = (item: RunDocumentSymbol) => props.projection.entries.find(entry => (
  (item.artifactId && entry.artifactId === item.artifactId)
  || (item.artifactKey && entry.artifactKey === item.artifactKey)
  || (item.semanticTaskKey && entry.kind === 'task' && entry.semanticTaskKey === item.semanticTaskKey)
)) || null

const selectSymbol = (item: RunDocumentSymbol) => {
  activeSymbolId.value = item.id
  emit('selectSymbol', item)
  if (item.semanticTaskKey) emit('selectSemanticTask', item.semanticTaskKey)
  if (item.type === 'artifact') {
    const entry = symbolEntry(item)
    if (entry) emit('openArtifact', entry)
  } else if (item.type === 'acg') {
    const entry = props.projection.entries.find(candidate => candidate.kind === 'graph')
    if (entry) emit('locateGraph', entry)
  }
}

const openSymbol = (item: RunDocumentSymbol) => {
  if (item.type === 'task' || item.type === 'acg-node') {
    emit('openSemanticTask', item.semanticTaskKey || null)
    return
  }
  if (item.type === 'artifact') {
    const entry = symbolEntry(item)
    if (entry) emit('openArtifact', entry)
    return
  }
  if (item.type === 'acg') {
    const entry = props.projection.entries.find(candidate => candidate.kind === 'graph')
    if (entry) emit('locateGraph', entry)
  }
}

const openMission = () => {
  const mission = props.projection.entries.find(entry => entry.kind === 'virtual_document' && entry.name === 'mission.md')
    || {
      entryId: 'overview:mission.md', kind: 'virtual_document' as const, name: 'mission.md', title: 'mission.md', group: 'overview', displayOrder: 0,
      content: props.projection.mission.goal
    }
  emit('openEntry', mission)
}

const locateBreadcrumb = (id: string) => {
  if (id === 'mission') {
    openMission()
    return
  }
  if (id === 'run') return
  const item = findRunDocumentSymbol(documentModel.value.symbols, id)
  if (item) selectSymbol(item)
}

const scrollBody = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const onScroll = () => {
  const el = scrollBody.value
  if (el) followLatest.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}
const scrollToLatest = async () => {
  followLatest.value = true
  await nextTick()
  const el = scrollBody.value
  if (el) el.scrollTop = el.scrollHeight
}
watch(documentModel, async () => {
  if (!followLatest.value) return
  await nextTick()
  const el = scrollBody.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<style scoped>
.run-progress { --run-content-max: 1440px; --run-content-inset: clamp(18px, 2.4vw, 34px); display: flex; flex: 1 1 auto; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0; color: var(--wb-text); }
.run-progress__document-head, .run-progress__toolbar { box-sizing: border-box; width: min(100%, var(--run-content-max)); margin-inline: auto; padding-inline: var(--run-content-inset); }
.run-progress__document-head { padding-bottom: 2px; }
.run-progress__header { display: grid; gap: 6px; padding-bottom: 14px; border-bottom: 1px solid var(--wb-border-soft); }
.run-progress__eyebrow { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .12em; }
.run-progress__heading-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.run-progress__heading-copy { min-width: 0; }
.run-progress__goal { margin: 0; color: var(--wb-text); font-size: 18px; font-weight: 650; line-height: 1.35; text-wrap: pretty; }
.run-progress__summary { max-width: min(900px, 100%); margin: 3px 0 0; overflow: hidden; color: var(--wb-text-secondary); font-size: 12px; line-height: 1.55; text-overflow: ellipsis; white-space: nowrap; }
.run-progress__mission-link { flex: 0 0 auto; padding: 3px 0; border: 0; color: var(--wb-accent); background: transparent; cursor: pointer; font: 10px var(--font-mono, monospace); }
.run-progress__mission-link:hover { text-decoration: underline; }
.run-progress__meta { display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px; margin-top: 4px; }
.run-progress__status { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.run-progress__status.is-completed { color: var(--wb-success); }
.run-progress__status.is-failed { color: var(--wb-danger); }
.run-progress__status.is-paused { color: var(--wb-warning); }
.run-progress__duration, .run-progress__runid { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.run-progress__runid { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-progress__empty { display: grid; flex: 1; place-items: center; color: var(--wb-text-muted); font-size: 12px; }
.run-progress__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0 7px; }
.run-progress__toolbar-label { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.run-progress__filter { display: flex; align-items: center; gap: 7px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.run-progress__filter input { width: 130px; padding: 4px 7px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); outline: 0; color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 10px var(--font-mono, monospace); }
.run-progress__filter input:focus { border-color: var(--wb-accent); }
.run-progress__body { position: relative; flex: 1; min-height: 0; overflow: auto; scrollbar-color: var(--wb-border-strong) transparent; scrollbar-width: thin; }
.run-progress__stream { box-sizing: border-box; width: max-content; min-width: 100%; min-height: 100%; padding-bottom: 42px; }
.run-progress__browser { display: flex; min-width: 100%; min-height: 100%; padding-inline: var(--run-content-inset); }
.run-progress__column { flex: 0 0 clamp(280px, 30vw, 380px); min-width: 0; min-height: 100%; border-right: 1px solid var(--wb-border-soft); }
.run-progress__column:first-child { border-left: 1px solid var(--wb-border-soft); }
.run-progress__column-head { padding: 9px 12px 8px; border-bottom: 1px solid var(--wb-border-soft); color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.run-progress__column-body { padding: 4px 8px 24px; }
.run-progress__detail { padding: 14px 16px 24px; }
.run-progress__detail-status { display: flex; align-items: center; gap: 8px; min-height: 28px; color: var(--wb-text); }
.run-progress__detail-status strong { font-size: 13px; font-weight: 650; }
.run-progress__detail-mark { width: 14px; color: var(--wb-text-muted); font: 12px var(--font-mono, monospace); text-align: center; }
.run-progress__detail-mark.is-running { color: var(--wb-accent); }
.run-progress__detail-mark.is-completed { color: var(--wb-success); }
.run-progress__detail-mark.is-warning { color: var(--wb-warning); }
.run-progress__detail-mark.is-failed { color: var(--wb-danger); }
.run-progress__detail-summary { margin: 5px 0 14px; color: var(--wb-text-secondary); font-size: 11px; line-height: 1.5; }
.run-progress__detail-list { margin: 0; border-top: 1px solid var(--wb-border-soft); }
.run-progress__detail-list > div { display: grid; grid-template-columns: minmax(80px, .65fr) minmax(0, 1.35fr); gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--wb-border-soft); }
.run-progress__detail-list dt { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.run-progress__detail-list dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--wb-text-secondary); font: 10px/1.45 var(--font-mono, monospace); }
.run-progress__detail-content { max-height: 360px; margin: 14px 0 0; padding: 10px 0; overflow: auto; border-top: 1px solid var(--wb-border-soft); color: var(--wb-text-secondary); background: transparent; font: 10px/1.5 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.run-progress__waiting { padding: 16px var(--run-content-inset); color: var(--wb-text-muted); font-size: 12px; }
.run-progress__follow { position: sticky; bottom: 10px; display: block; margin: 0 auto; padding: 5px 14px; border: 1px solid color-mix(in srgb, var(--wb-accent) 34%, var(--wb-border)); border-radius: 999px; color: var(--wb-accent); background: var(--wb-surface-2); cursor: pointer; font-size: 11px; box-shadow: 0 2px 8px rgb(0 0 0 / 18%); }

@media (max-width: 680px) {
  .run-progress { --run-content-inset: 16px; }
  .run-progress__heading-row { display: grid; gap: 8px; }
  .run-progress__summary { white-space: normal; }
  .run-progress__mission-link { justify-self: start; }
}
</style>
