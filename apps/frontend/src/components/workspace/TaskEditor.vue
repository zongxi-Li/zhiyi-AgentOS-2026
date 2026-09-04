<template>
  <section class="task-editor" aria-label="Semantic task editor">
    <header class="task-editor__header">
      <div class="task-editor__title">
        <span class="task-editor__eyebrow">TASK</span>
        <strong>{{ entry.name }}</strong>
        <small>{{ entry.semanticTaskKey || 'legacy task identity' }}</small>
      </div>
      <div class="task-editor__actions">
        <span class="task-editor__status" :class="`is-${entry.status || 'pending'}`">{{ statusLabel(entry.status) }}</span>
        <button type="button" :disabled="!graphNode" @click="emit('locateGraph')">在图中定位</button>
      </div>
    </header>

    <div class="task-editor__body">
      <section class="task-editor__section task-editor__section--objective">
        <div class="task-editor__section-heading">OBJECTIVE</div>
        <p class="task-editor__objective">{{ entry.objective || '当前规划快照未提供 objective。' }}</p>
      </section>

      <section class="task-editor__section task-editor__section--overview">
        <div class="task-editor__section-heading">
          <span>EXECUTION OVERVIEW</span>
          <strong>{{ statusLabel(entry.status) }}</strong>
        </div>
        <div class="task-editor__stats">
          <div><span>Attempts</span><strong>{{ entry.attemptCount ?? 0 }}</strong></div>
          <div><span>Trace</span><strong>{{ traceCount === null ? '—' : traceCount }}</strong></div>
          <div><span>Communication</span><strong>{{ communicationCount === null ? '—' : communicationCount }}</strong></div>
          <div><span>Artifacts</span><strong>{{ artifacts.length }}</strong></div>
        </div>
      </section>

      <section v-if="stageOutputAvailable" class="task-editor__section task-editor__section--stage-output">
        <div class="task-editor__section-heading">
          <span>STAGE OUTPUT / 阶段结果</span>
          <strong>{{ stageOutputPhase }}</strong>
        </div>
        <pre v-if="stageOutputContent" data-testid="task-stage-output">{{ stageOutputContent }}</pre>
        <p v-else-if="stageOutputLoading" class="task-editor__muted">正在读取已持久化的阶段结果…</p>
        <p v-else class="task-editor__muted">{{ stageOutputError || '等待模型输出…' }}</p>
      </section>

      <section class="task-editor__section">
        <div class="task-editor__section-heading">ARTIFACTS <span>{{ artifacts.length }}</span></div>
        <div v-if="artifacts.length" class="task-editor__artifacts">
          <button v-for="artifact in artifacts" :key="artifact.entryId" type="button" @click="emit('openArtifact', artifact)">
            <span>{{ artifact.name }}</span>
            <code>{{ artifact.artifactKey }}</code>
          </button>
        </div>
        <p v-else class="task-editor__muted">当前 Task 尚无 Artifact。</p>
      </section>

      <section class="task-editor__section">
        <div class="task-editor__section-heading">IDENTITY</div>
        <dl class="task-editor__properties">
          <div><dt>semanticTaskKey</dt><dd class="is-code">{{ entry.semanticTaskKey || 'legacy / 未观测' }}</dd></div>
          <div><dt>taskId</dt><dd class="is-code">{{ entry.taskId || '未观测' }}</dd></div>
          <div><dt>logicalRole</dt><dd>{{ entry.logicalRole || 'task' }}</dd></div>
          <div><dt>acgNodeId</dt><dd class="is-code">{{ graphNode?.acgNodeId || entry.acgNodeId || '未观测' }}</dd></div>
        </dl>
      </section>

      <section class="task-editor__section task-editor__section--execution">
        <div class="task-editor__section-heading">EXECUTION DETAILS</div>
        <dl class="task-editor__properties">
          <div><dt>status</dt><dd>{{ statusLabel(entry.status) }}</dd></div>
          <div><dt>attempts</dt><dd>{{ entry.attemptCount ?? 0 }}</dd></div>
          <div><dt>latestAttemptId</dt><dd class="is-code">{{ entry.latestAttemptId || '未观测' }}</dd></div>
          <div><dt>Trace</dt><dd>{{ traceCount === null ? '未观测' : traceCount }}</dd></div>
          <div><dt>Communication</dt><dd>{{ communicationCount === null ? '未观测' : communicationCount }}</dd></div>
        </dl>
      </section>

      <section class="task-editor__section">
        <div class="task-editor__section-heading">DEPENDENCIES</div>
        <div v-if="entry.dependencyKeys?.length" class="task-editor__chips">
          <code v-for="dependency in entry.dependencyKeys" :key="dependency">{{ dependency }}</code>
        </div>
        <p v-else class="task-editor__muted">无已声明依赖。</p>
      </section>

      <section class="task-editor__section">
        <div class="task-editor__section-heading">RESOURCE BINDING</div>
        <dl class="task-editor__properties">
          <div><dt>Agent</dt><dd>{{ binding?.agentId || '未观测' }}</dd></div>
          <div><dt>Model</dt><dd>{{ binding?.modelId || '未观测' }}</dd></div>
          <div><dt>Resource</dt><dd>{{ binding?.resourceId || '未观测' }}</dd></div>
          <div><dt>health</dt><dd>{{ resourceHealth }}</dd></div>
        </dl>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { agentosApi } from '@/services/api/agentos'
import type {
  MissionWorkspaceProjection,
  ResourceBindingObservation,
  ResourceObservation,
  WorkspaceEntry,
  WorkspaceGraphNode
} from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'

const props = defineProps<{
  entry: WorkspaceEntry
  projection: MissionWorkspaceProjection
  graphNodes: WorkspaceGraphNode[]
  runtimeObservation: RuntimeObservation | null
  runtimeStore?: RuntimeEventStore | null
}>()

const emit = defineEmits<{
  locateGraph: []
  openArtifact: [entry: WorkspaceEntry]
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
const stageOutputPhase = computed(() => liveNode.value?.phase || (persistedStageOutput.value ? 'PERSISTED' : 'WAITING'))

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
  pending: 'pending',
  ready: 'ready',
  running: 'running',
  completed: 'completed',
  failed: 'failed',
  skipped: 'skipped'
}[status || ''] || status || 'pending')
</script>

<style scoped>
.task-editor { display: flex; flex: 1 1 auto; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-section); background: var(--wb-surface-section); color: var(--wb-text); box-shadow: var(--wb-shadow-section); }
.task-editor__header { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 54px; padding: 9px 16px; border-bottom: 1px solid var(--wb-border-soft); background: var(--wb-surface-section); }
.task-editor__title { min-width: 0; }
.task-editor__eyebrow { display: block; color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.task-editor__title strong, .task-editor__title small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-editor__title strong { margin: 3px 0; font-size: 14px; }
.task-editor__title small { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.task-editor__actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.task-editor__status { color: var(--wb-text-secondary); font: 10px var(--font-mono, monospace); }
.task-editor__status.is-completed { color: var(--wb-success); }
.task-editor__status.is-failed { color: var(--wb-danger); }
.task-editor__status.is-running { color: var(--wb-accent); }
.task-editor__actions button { min-height: 28px; padding: 0 9px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: transparent; cursor: pointer; font-size: 11px; }
.task-editor__actions button:hover:not(:disabled) { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 42%, var(--wb-border)); background: var(--wb-accent-soft); }
.task-editor__actions button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 1px; }
.task-editor__actions button:disabled { color: var(--text-disabled); cursor: not-allowed; }
.task-editor__body { flex: 1; min-height: 0; padding: 18px 22px 42px; overflow-y: auto; scrollbar-gutter: stable; }
.task-editor__section { max-width: 840px; margin: 0 auto; padding: 0; }
.task-editor__section + .task-editor__section { margin-top: 14px; }
.task-editor__section-heading { display: flex; justify-content: space-between; margin-bottom: 9px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.task-editor__section-heading > span { color: var(--wb-text-muted); }
.task-editor__section-heading > strong { color: var(--wb-text-secondary); font-weight: 500; letter-spacing: 0; text-transform: none; }
.task-editor__section--objective,
.task-editor__section--overview,
.task-editor__section--execution { padding: 13px 14px 14px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-section); background: var(--wb-surface-pane); box-shadow: var(--wb-shadow-section); }
.task-editor__section--stage-output { padding: 13px 14px 14px; border: 1px solid color-mix(in srgb, var(--wb-accent) 26%, var(--wb-border-soft)); border-radius: var(--wb-radius-section); background: var(--wb-surface-pane); }
.task-editor__section--stage-output pre { max-height: 360px; margin: 0; padding: 12px; overflow: auto; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-md); background: var(--wb-surface-inset); color: var(--wb-text); font: 11px/1.6 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.task-editor__section--objective { padding-bottom: 16px; }
.task-editor__section--objective .task-editor__section-heading { color: var(--wb-accent); }
.task-editor__objective { max-width: 760px; margin: 0; color: var(--wb-text); font-size: 14px; line-height: 1.72; white-space: pre-wrap; }
.task-editor__stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-md); background: var(--wb-surface-inset); }
.task-editor__stats > div { display: grid; gap: 4px; min-width: 0; padding: 9px 10px; border-right: 1px solid color-mix(in srgb, var(--wb-border) 74%, transparent); }
.task-editor__stats > div:last-child { border-right: 0; }
.task-editor__stats span { overflow: hidden; color: var(--wb-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.task-editor__stats strong { color: var(--wb-text); font: 12px var(--font-mono, monospace); }
.task-editor__properties { margin: 0; }
.task-editor__properties > div { display: grid; grid-template-columns: minmax(120px, 35%) minmax(0, 1fr); gap: 12px; padding: 7px 0; font-size: 12px; }
.task-editor__properties > div + div { border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.task-editor__properties dt { color: var(--wb-text-muted); }
.task-editor__properties dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--wb-text-secondary); text-align: right; }
.task-editor__properties dd.is-code, .task-editor__chips code, .task-editor__artifacts code { color: var(--wb-text); font: 10px var(--font-mono, monospace); }
.task-editor__muted { margin: 0; color: var(--wb-text-muted); font-size: 12px; }
.task-editor__chips { display: flex; gap: 6px; flex-wrap: wrap; }
.task-editor__chips code { padding: 5px 7px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); background: var(--wb-surface-inset); }
.task-editor__artifacts { display: grid; gap: 5px; }
.task-editor__artifacts button { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 34px; padding: 0 10px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: transparent; cursor: pointer; text-align: left; }
.task-editor__artifacts button:hover { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 42%, var(--wb-border)); background: var(--wb-accent-soft); }
.task-editor__artifacts button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 1px; }
.task-editor__artifacts code { color: var(--wb-text-muted); }
@media (max-width: 720px) {
  .task-editor__header { align-items: flex-start; flex-direction: column; gap: 8px; }
  .task-editor__body { padding: 16px 14px 36px; }
  .task-editor__stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-editor__stats > div:nth-child(2) { border-right: 0; }
  .task-editor__stats > div:nth-child(-n + 2) { border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 74%, transparent); }
}
</style>
