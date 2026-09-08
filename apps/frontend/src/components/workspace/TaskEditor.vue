<template>
  <section class="task-editor" aria-label="Semantic task editor">
    <header class="task-editor__header">
      <div class="task-editor__heading">
        <nav class="task-editor__breadcrumb" aria-label="Task breadcrumb">
          <button type="button" @click="openMission">{{ missionTitle }}</button>
          <span aria-hidden="true">›</span>
          <span>Run {{ runNumber }}</span>
          <span aria-hidden="true">›</span>
          <span>Task {{ taskNumber }}</span>
        </nav>
        <span class="task-editor__eyebrow">TASK</span>
        <strong>{{ entry.name }}</strong>
        <small>{{ entry.semanticTaskKey || 'legacy task identity' }}</small>
        <div class="task-editor__status-line">
          <span class="task-editor__status-mark" :class="`is-${entry.status || 'pending'}`" aria-hidden="true">{{ statusMark(entry.status) }}</span>
          <span class="task-editor__status" :class="`is-${entry.status || 'pending'}`">{{ statusLabel(entry.status) }}</span>
          <span>Attempt {{ entry.attemptCount ?? 0 }}</span>
          <span v-if="durationText">{{ durationText }}</span>
        </div>
      </div>
      <div class="task-editor__actions">
        <button type="button" :disabled="!graphNode" @click="emit('locateGraph')">在图中定位</button>
      </div>
    </header>

    <div class="task-editor__body">
      <div class="task-editor__content" :style="{ width: `${contentWidth}px` }">
      <section class="task-editor__section task-editor__section--contract">
        <div class="task-editor__section-heading"><span>CONTRACT</span></div>
        <div class="task-editor__symbol-heading"><span aria-hidden="true">▾</span><strong>Objective</strong></div>
        <p class="task-editor__objective">{{ entry.objective || '当前规划快照未提供 objective。' }}</p>
        <div v-if="entry.dependencyKeys?.length" class="task-editor__inline-row">
          <span class="task-editor__inline-label">Inputs</span>
          <code v-for="dependency in entry.dependencyKeys" :key="dependency">{{ dependency }}</code>
        </div>
      </section>

      <section v-if="stageOutputAvailable" class="task-editor__section task-editor__section--result">
        <div class="task-editor__section-heading"><span>RESULT</span></div>
        <StageOutputRenderer
          v-if="stageOutputContent"
          :value="stageOutputContent"
          :selected-id="selectedSymbolId"
          :id-prefix="resultIdPrefix"
          @select="selectResultItem"
          @reference="selectResultItem"
        />
        <p v-else-if="stageOutputLoading" class="task-editor__muted">正在读取已持久化的阶段结果…</p>
        <p v-else class="task-editor__muted">{{ stageOutputError || '等待模型输出…' }}</p>
      </section>

      <section class="task-editor__section task-editor__section--artifacts">
        <div class="task-editor__section-heading">
          <span>ARTIFACTS</span>
          <span class="task-editor__section-meta">{{ artifacts.length }}</span>
        </div>
        <div v-if="artifacts.length" class="task-editor__artifacts">
          <button v-for="artifact in artifacts" :key="artifact.entryId" type="button" @click="emit('openArtifact', artifact)">
            <span>{{ artifact.name }}</span>
            <code>{{ artifact.artifactKey }}</code>
          </button>
        </div>
        <p v-else class="task-editor__muted">当前 Task 尚无 Artifact。</p>
      </section>

      <section class="task-editor__section task-editor__section--fold">
        <button type="button" class="task-editor__fold-heading" :aria-expanded="executionExpanded" @click="executionExpanded = !executionExpanded">
          <span><span class="task-editor__fold-mark" aria-hidden="true">{{ executionExpanded ? '▾' : '▸' }}</span> EXECUTION</span>
          <span class="task-editor__section-meta">{{ executionSummary }}</span>
        </button>
        <div v-if="executionExpanded" class="task-editor__fold-body">
          <div class="task-editor__metadata-line">
            <span>Attempt {{ entry.attemptCount ?? 0 }}</span>
            <span>{{ statusLabel(entry.status) }}</span>
            <span v-if="durationText">{{ durationText }}</span>
            <span v-if="binding?.agentId">Agent: {{ binding.agentId }}</span>
            <span v-if="binding?.modelId">Model: {{ binding.modelId }}</span>
          </div>
          <dl class="task-editor__properties">
            <div><dt>latestAttemptId</dt><dd class="is-code">{{ entry.latestAttemptId || '未观测' }}</dd></div>
            <div><dt>semanticTaskKey</dt><dd class="is-code">{{ entry.semanticTaskKey || 'legacy / 未观测' }}</dd></div>
            <div><dt>taskId</dt><dd class="is-code">{{ entry.taskId || '未观测' }}</dd></div>
            <div><dt>acgNodeId</dt><dd class="is-code">{{ graphNode?.acgNodeId || entry.acgNodeId || '未观测' }}</dd></div>
            <div><dt>Resource</dt><dd>{{ binding?.resourceId || '未观测' }} · {{ resourceHealth }}</dd></div>
          </dl>
        </div>
      </section>

      <section class="task-editor__section task-editor__section--fold">
        <button type="button" class="task-editor__fold-heading" :aria-expanded="evidenceExpanded" @click="evidenceExpanded = !evidenceExpanded">
          <span><span class="task-editor__fold-mark" aria-hidden="true">{{ evidenceExpanded ? '▾' : '▸' }}</span> EVIDENCE</span>
          <span class="task-editor__section-meta">{{ evidenceSummary }}</span>
        </button>
        <div v-if="evidenceExpanded" class="task-editor__fold-body">
          <div class="task-editor__metadata-line">
            <span>{{ traceCount === null ? '未观测' : `${traceCount} traces` }}</span>
            <span>{{ communicationCount === null ? '未观测' : `${communicationCount} communications` }}</span>
          </div>
        </div>
      </section>
      <button
        class="task-editor__resize-handle"
        type="button"
        role="separator"
        aria-label="调整内容宽度"
        aria-orientation="vertical"
        :aria-valuemin="TASK_CONTENT_WIDTH_MIN"
        :aria-valuemax="TASK_CONTENT_WIDTH_MAX"
        :aria-valuenow="contentWidth"
        title="拖动调整内容宽度，双击恢复默认"
        @pointerdown="startResize"
        @keydown="onResizeKeydown"
        @dblclick="resetContentWidth"
      />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { agentosApi } from '@/services/api/agentos'
import StageOutputRenderer, { type StageOutputSelection } from './StageOutputRenderer.vue'
import type {
  MissionWorkspaceProjection,
  ResourceBindingObservation,
  ResourceObservation,
  WorkspaceEntry,
  WorkspaceGraphNode
} from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'

const props = defineProps<{
  entry: WorkspaceEntry
  projection: MissionWorkspaceProjection
  graphNodes: WorkspaceGraphNode[]
  selectedSymbolId?: string | null
  runtimeObservation: RuntimeObservation | null
  runtimeStore?: RuntimeEventStore | null
}>()

const emit = defineEmits<{
  locateGraph: []
  openArtifact: [entry: WorkspaceEntry]
  openEntry: [entry: WorkspaceEntry]
  selectSymbol: [symbol: RunDocumentSymbol]
}>()

const graphNode = computed(() => props.graphNodes.find(node => (
  (props.entry.semanticTaskKey && node.semanticTaskKey === props.entry.semanticTaskKey)
  || (props.entry.acgNodeId && node.acgNodeId === props.entry.acgNodeId)
)) || null)
const artifacts = computed(() => props.projection.entries
  .filter(item => item.kind === 'artifact' && item.semanticTaskKey === props.entry.semanticTaskKey)
  .sort((left, right) => left.displayOrder - right.displayOrder || left.entryId.localeCompare(right.entryId)))
const liveNode = computed(() => {
  const nodeId = graphNode.value?.acgNodeId || props.entry.acgNodeId
  return nodeId ? props.runtimeStore?.nodes[nodeId] || null : null
})
const outputRef = computed(() => {
  const value = props.entry.metadata?.outputRef
  return typeof value === 'string' && value ? value : null
})
const outputRunId = computed(() => props.entry.runId || props.projection.activeRun?.runId || null)
const persistedStageOutput = ref('')
const stageOutputLoading = ref(false)
const stageOutputError = ref('')
const executionExpanded = ref(!['completed', 'succeeded', 'failed', 'cancelled'].includes(props.entry.status || ''))
const evidenceExpanded = ref(false)
const TASK_CONTENT_WIDTH_KEY = 'kinlin.task-editor.content-width'
const TASK_CONTENT_WIDTH_DEFAULT = 1480
const TASK_CONTENT_WIDTH_MIN = 720
const TASK_CONTENT_WIDTH_MAX = 1900

const readContentWidth = () => {
  if (typeof window === 'undefined') return TASK_CONTENT_WIDTH_DEFAULT
  try {
    const stored = Number(window.localStorage.getItem(TASK_CONTENT_WIDTH_KEY))
    return Number.isFinite(stored)
      ? Math.min(TASK_CONTENT_WIDTH_MAX, Math.max(TASK_CONTENT_WIDTH_MIN, stored))
      : TASK_CONTENT_WIDTH_DEFAULT
  } catch {
    return TASK_CONTENT_WIDTH_DEFAULT
  }
}
const contentWidth = ref(readContentWidth())
const setContentWidth = (value: number) => {
  contentWidth.value = Math.round(Math.min(TASK_CONTENT_WIDTH_MAX, Math.max(TASK_CONTENT_WIDTH_MIN, value)) / 20) * 20
  try { window.localStorage.setItem(TASK_CONTENT_WIDTH_KEY, String(contentWidth.value)) } catch { /* storage is optional */ }
}
const resetContentWidth = () => setContentWidth(TASK_CONTENT_WIDTH_DEFAULT)
let resizeStart: { x: number; width: number } | null = null
const onResizePointerMove = (event: PointerEvent) => {
  if (!resizeStart) return
  setContentWidth(resizeStart.width + event.clientX - resizeStart.x)
}
const stopResize = () => {
  resizeStart = null
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointerup', stopResize)
  document.body.classList.remove('task-editor-is-resizing')
}
const startResize = (event: PointerEvent) => {
  if (event.button !== 0) return
  resizeStart = { x: event.clientX, width: contentWidth.value }
  window.addEventListener('pointermove', onResizePointerMove)
  window.addEventListener('pointerup', stopResize)
  document.body.classList.add('task-editor-is-resizing')
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
  event.preventDefault()
}
const onResizeKeydown = (event: KeyboardEvent) => {
  if (event.key === 'ArrowLeft') {
    setContentWidth(contentWidth.value - 40)
    event.preventDefault()
  } else if (event.key === 'ArrowRight') {
    setContentWidth(contentWidth.value + 40)
    event.preventDefault()
  } else if (event.key === 'Home') {
    resetContentWidth()
    event.preventDefault()
  }
}

const formatStageOutput = (value: unknown) => {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return String(value ?? '') }
}
watch([outputRunId, outputRef], async ([runId, refValue], _previous, onCleanup) => {
  persistedStageOutput.value = ''
  stageOutputError.value = ''
  stageOutputLoading.value = false
  if (!runId || !refValue) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  stageOutputLoading.value = true
  try {
    const result = await agentosApi.getRunOutput(runId, refValue, { signal: controller.signal })
    persistedStageOutput.value = formatStageOutput(result.content)
  } catch (error) {
    if (!controller.signal.aborted) stageOutputError.value = '阶段结果暂时无法读取。'
  } finally {
    if (!controller.signal.aborted) stageOutputLoading.value = false
  }
}, { immediate: true })

const stageOutputContent = computed(() => liveNode.value?.outputBuffer || persistedStageOutput.value)
const stageOutputAvailable = computed(() => Boolean(
  outputRef.value || liveNode.value || stageOutputLoading.value || stageOutputError.value
))
const resultIdPrefix = computed(() => `task-result:${props.entry.semanticTaskKey || props.entry.entryId}`)

const resourceObservation = computed<ResourceObservation | null>(() => props.runtimeObservation?.resourceObservation || null)
const binding = computed<ResourceBindingObservation | null>(() => {
  const observation = resourceObservation.value
  if (!observation) return null
  return observation.bindings.find(item => (
    (props.entry.latestAttemptId && item.attemptId === props.entry.latestAttemptId)
    || (graphNode.value?.acgNodeId && item.acgNodeId === graphNode.value.acgNodeId)
  )) || null
})
const resourceHealth = computed(() => {
  if (!binding.value || !resourceObservation.value) return '未观测'
  const health = resourceObservation.value.items.find(item => item.profile.resourceId === binding.value?.resourceId)?.snapshot.healthStatus
  return health === 'unknown' || !health ? 'Unknown / 未知' : health
})
const traceCount = computed(() => {
  if (!props.runtimeObservation || !graphNode.value) return null
  return props.runtimeObservation.traces.filter(item => item.stepId === graphNode.value?.acgNodeId).length
})
const communicationCount = computed(() => {
  if (!props.runtimeObservation || !graphNode.value) return null
  return props.runtimeObservation.communication.filter(item => (
    item.producerStepId === graphNode.value?.acgNodeId
    || item.consumerStepId === graphNode.value?.acgNodeId
  )).length
})

const statusLabel = (status?: string | null) => ({
  pending: 'Pending',
  ready: 'Ready',
  running: 'Running',
  completed: 'Completed',
  succeeded: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  skipped: 'Skipped'
}[status || ''] || status || 'Pending')
const statusMark = (status?: string | null) => {
  if (['completed', 'succeeded'].includes(status || '')) return '✓'
  if (['failed', 'cancelled'].includes(status || '')) return '×'
  if (['running', 'ready'].includes(status || '')) return '●'
  return '○'
}
const shorten = (value: string, length: number) => value.length > length ? `${value.slice(0, length)}…` : value
const missionTitle = computed(() => shorten((props.projection.mission.goal || props.projection.mission.description || 'Mission').split(/[\n。！？!?]/)[0].trim(), 34))
const runId = computed(() => props.entry.runId || props.projection.activeRun?.runId || null)
const runNumber = computed(() => {
  const index = props.projection.runs.findIndex(run => run.runId === runId.value)
  return String(index >= 0 ? index + 1 : 1).padStart(2, '0')
})
const taskNumber = computed(() => {
  const tasks = props.projection.entries.filter(item => item.kind === 'task').sort((left, right) => left.displayOrder - right.displayOrder)
  const index = tasks.findIndex(item => item.entryId === props.entry.entryId)
  return String(index >= 0 ? index + 1 : 1).padStart(2, '0')
})
const durationText = computed(() => {
  const run = props.projection.runs.find(item => item.runId === runId.value)
  if (!run?.createdAt) return null
  const start = new Date(run.createdAt).getTime()
  const end = run.completedAt ? new Date(run.completedAt).getTime() : Date.now()
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  const seconds = Math.max(0, (end - start) / 1000)
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s` : `${Number(seconds.toFixed(1))}s`
})
const executionSummary = computed(() => [
  `Attempt ${props.entry.attemptCount ?? 0}`,
  statusLabel(props.entry.status),
  durationText.value,
  binding.value?.agentId ? `Agent: ${binding.value.agentId}` : null
].filter(Boolean).join(' · '))
const evidenceSummary = computed(() => [
  traceCount.value === null ? null : `${traceCount.value} traces`,
  communicationCount.value === null ? null : `${communicationCount.value} communications`
].filter(Boolean).join(' · ') || '未观测')

const resultSymbol = (selection: StageOutputSelection): RunDocumentSymbol => ({
  id: `${resultIdPrefix.value}:${selection.sectionKey}:${selection.index}`,
  type: 'result',
  status: 'completed',
  title: selection.title,
  subtitle: selection.source ? `${selection.sectionKey} · ${selection.source}` : selection.sectionKey,
  detail: selection.source ? `Reference ${selection.source}` : selection.sectionKey,
  runId: outputRunId.value || '',
  semanticTaskKey: props.entry.semanticTaskKey,
  graphNodeId: graphNode.value?.acgNodeId,
  children: [],
  content: formatStageOutput(selection.value)
})
const selectResultItem = (selection: StageOutputSelection) => emit('selectSymbol', resultSymbol(selection))
const openMission = () => emit('openEntry', {
  entryId: 'overview:mission.md',
  kind: 'virtual_document',
  name: 'mission.md',
  title: 'mission.md',
  group: 'overview',
  displayOrder: 0,
  content: props.projection.mission.goal
})
onBeforeUnmount(stopResize)
</script>

<style scoped>
.task-editor { display: flex; flex: 1 1 auto; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; background: var(--wb-surface-shell); color: var(--wb-text); }
.task-editor__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 10px 20px 9px; border-bottom: 1px solid var(--wb-border-soft); background: var(--wb-surface-shell); }
.task-editor__heading { min-width: 0; }
.task-editor__breadcrumb { display: flex; align-items: center; gap: 7px; margin-bottom: 7px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.task-editor__breadcrumb button { padding: 0; border: 0; color: var(--wb-text-secondary); background: transparent; cursor: pointer; font: inherit; }
.task-editor__breadcrumb button:hover { color: var(--wb-accent); text-decoration: underline; }
.task-editor__eyebrow { display: block; color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.task-editor__heading > strong, .task-editor__heading > small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-editor__heading > strong { margin: 2px 0; font-size: 16px; }
.task-editor__heading > small { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.task-editor__status-line { display: flex; align-items: center; flex-wrap: wrap; gap: 0; margin-top: 6px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.task-editor__status-line > .task-editor__status ~ span::before { content: '·'; margin: 0 9px; color: var(--wb-text-muted); }
.task-editor__status-mark { margin-right: 7px; color: var(--wb-text-muted); }
.task-editor__status-mark.is-completed { color: var(--wb-success); }
.task-editor__status-mark.is-failed, .task-editor__status-mark.is-cancelled { color: var(--wb-danger); }
.task-editor__status-mark.is-running { color: var(--wb-accent); }
.task-editor__status.is-completed { color: var(--wb-success); }
.task-editor__status.is-failed, .task-editor__status.is-cancelled { color: var(--wb-danger); }
.task-editor__status.is-running { color: var(--wb-accent); }
.task-editor__actions { display: flex; flex: 0 0 auto; align-items: center; }
.task-editor__actions button { min-height: 28px; padding: 0 9px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: transparent; cursor: pointer; font-size: 11px; }
.task-editor__actions button:hover:not(:disabled) { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 42%, var(--wb-border)); background: var(--wb-accent-soft); }
.task-editor__actions button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 1px; }
.task-editor__actions button:disabled { color: var(--text-disabled); cursor: not-allowed; }
.task-editor__body { flex: 1; min-height: 0; padding: 22px clamp(18px, 2.4vw, 42px) 42px; overflow-y: auto; scrollbar-gutter: stable; }
.task-editor__content { position: relative; width: 1480px; max-width: 100%; margin: 0 auto; }
.task-editor__section { max-width: none; margin: 0; padding: 0 0 10px; border-bottom: 1px solid var(--wb-border-soft); }
.task-editor__section + .task-editor__section { margin-top: 24px; }
.task-editor__section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); letter-spacing: .1em; }
.task-editor__section-meta { color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); letter-spacing: 0; }
.task-editor__symbol-heading { display: flex; align-items: center; gap: 7px; margin-left: 8px; color: var(--wb-text-secondary); font-size: 13px; }
.task-editor__symbol-heading > span { color: var(--wb-accent); font: 11px var(--font-mono, monospace); }
.task-editor__symbol-heading strong { font-weight: 650; }
.task-editor__objective { max-width: 1260px; margin: 7px 0 0 29px; color: var(--wb-text); font-size: 15px; line-height: 1.7; white-space: pre-wrap; }
.task-editor__inline-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 9px; margin: 11px 0 0 29px; color: var(--wb-text-muted); font-size: 11px; }
.task-editor__inline-label { font: 10px var(--font-mono, monospace); }
.task-editor__inline-row code { padding: 2px 5px; color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 10px var(--font-mono, monospace); }
.task-editor__section--result { padding-bottom: 10px; }
.task-editor__section--artifacts { padding-bottom: 10px; }
.task-editor__muted { margin: 0; color: var(--wb-text-muted); font-size: 12px; }
.task-editor__artifacts { display: grid; gap: 5px; margin-left: 18px; }
.task-editor__artifacts button { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 30px; padding: 0 8px; border: 0; border-bottom: 1px solid var(--wb-border-soft); color: var(--wb-text-secondary); background: transparent; cursor: pointer; text-align: left; }
.task-editor__artifacts button:hover { color: var(--wb-accent); background: var(--wb-hover); }
.task-editor__artifacts button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -1px; }
.task-editor__artifacts code { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.task-editor__section--fold { padding-bottom: 0; border-bottom: 0; }
.task-editor__fold-heading { display: flex; align-items: baseline; justify-content: space-between; width: 100%; padding: 0; border: 0; color: var(--wb-text-secondary); background: transparent; cursor: pointer; font: 10px var(--font-mono, monospace); letter-spacing: .1em; text-align: left; }
.task-editor__fold-heading:hover { color: var(--wb-text); }
.task-editor__fold-heading:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 3px; }
.task-editor__fold-mark { display: inline-block; width: 15px; color: var(--wb-accent); }
.task-editor__fold-body { margin: 9px 0 0 18px; padding: 9px 0 0; border-top: 1px solid var(--wb-border-soft); }
.task-editor__metadata-line { display: flex; align-items: center; flex-wrap: wrap; gap: 7px 12px; color: var(--wb-text-secondary); font: 10px var(--font-mono, monospace); }
.task-editor__metadata-line span + span::before { content: '·'; margin-right: 12px; color: var(--wb-text-muted); }
.task-editor__properties { margin: 8px 0 0; }
.task-editor__properties > div { display: grid; grid-template-columns: minmax(130px, 28%) minmax(0, 1fr); gap: 12px; padding: 5px 0; font-size: 11px; }
.task-editor__properties > div + div { border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.task-editor__properties dt { color: var(--wb-text-muted); }
.task-editor__properties dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--wb-text-secondary); text-align: right; }
.task-editor__properties dd.is-code { color: var(--wb-text); font: 10px var(--font-mono, monospace); }
.task-editor__resize-handle { position: absolute; z-index: 2; top: 0; right: -10px; width: 20px; height: 100%; min-height: 160px; padding: 0; border: 0; color: transparent; background: transparent; cursor: ew-resize; touch-action: none; }
.task-editor__resize-handle::after { content: ''; position: absolute; top: 36px; right: 9px; width: 2px; height: 48px; border-radius: 2px; background: var(--wb-border-strong); opacity: 0; transition: opacity 140ms var(--ease-out), background-color 140ms var(--ease-out); }
.task-editor__resize-handle:hover::after, .task-editor__resize-handle:focus-visible::after { background: var(--wb-accent); opacity: 1; }
.task-editor__resize-handle:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: -1px; }
:global(body.task-editor-is-resizing) { cursor: ew-resize; user-select: none; }
@media (max-width: 720px) {
  .task-editor__header { align-items: flex-start; flex-direction: column; gap: 10px; }
  .task-editor__body { padding: 16px 14px 36px; }
  .task-editor__resize-handle { display: none; }
  .task-editor__objective, .task-editor__inline-row { margin-left: 22px; }
  .task-editor__properties > div { grid-template-columns: minmax(100px, 38%) minmax(0, 1fr); gap: 8px; }
}
</style>
