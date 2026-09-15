<template>
  <aside class="runtime-inspector" aria-label="Workspace Secondary Sidebar">
    <SecondarySidebar
      v-if="secondarySidebarViews.length"
      :registry="registry"
      :context="inspectorContext"
      :title="inspectorTitle"
      :historical="historical"
      :component-props="baseProps"
      @locate-graph="emit('locateGraph')"
    />
    <InspectorFrame v-else-if="inspectorContribution || inspectorSections.length" :title="inspectorTitle" :historical="historical">
      <div v-if="inspectorSummary" class="runtime-inspector__summary">
        <div class="runtime-inspector__summary-line">
          <span v-if="inspectorSummary.role" class="runtime-inspector__role">{{ inspectorSummary.role }}</span>
          <span v-if="inspectorSummary.status" class="runtime-inspector__status" :class="`is-${inspectorSummary.statusTone}`">
            <i aria-hidden="true"></i>{{ inspectorSummary.status }}
          </span>
          <span class="runtime-inspector__artifact">
            {{ inspectorSummary.artifactCount ? `${inspectorSummary.artifactCount} 个 Artifact` : '无 Artifact' }}
          </span>
        </div>
        <code v-if="inspectorSummary.key" class="runtime-inspector__key">{{ inspectorSummary.key }}</code>
      </div>
      <InspectorSection v-if="graphNode && safeLiveOutput" title="Structured Output" :badge="liveNode?.phase || 'safe projection'">
        <pre class="runtime-output" data-testid="formal-live-output">{{ safeLiveOutput }}</pre>
      </InspectorSection>
      <component
        v-for="section in inspectorSections"
        :key="section.id"
        :is="section.component"
        v-bind="sectionProps(section)"
        @locate-graph="emit('locateGraph')"
      />
      <component
        v-if="!inspectorSections.length && inspectorContribution"
        :is="inspectorContribution.component"
        v-bind="baseProps"
        @locate-graph="emit('locateGraph')"
      />
    </InspectorFrame>
    <div v-else class="runtime-inspector__empty">选择一个 Workspace Symbol 查看属性。</div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { AcgBlueprint, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { WorkbenchContributionRegistry } from '@/workbench/registry'
import InspectorFrame from '@/components/workbench/InspectorFrame.vue'
import SecondarySidebar from '@/components/workbench/SecondarySidebar.vue'
import type { WorkbenchContext, WorkbenchInspectorContext } from '@/workbench/types'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'
import { safeStructuredOutput } from '@/workbench/runtime/runDocument'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import {
  RunRuntimeStore,
  acquireRunRuntimeStore,
  releaseRunRuntimeStore
} from '@/workbench/runtime/runtimeEvents'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'

const props = defineProps<{
  registry: WorkbenchContributionRegistry
  workbenchContext: WorkbenchContext
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
  selectedSymbol?: RunDocumentSymbol | null
  graphNodes: WorkspaceGraphNode[]
  available: boolean
  runId: string | null
  missionId: string
  graph: AcgBlueprint | null
  runStatus: string | null
  historical: boolean
  runtimeStore?: RuntimeEventStore | null
}>()
const ownedRuntimeStore = shallowRef<RunRuntimeStore | null>(null)
const ownedRunId = ref<string | null>(null)
const runtimeStore = computed(() => props.runtimeStore || ownedRuntimeStore.value)
const liveNode = computed(() => props.graphNode?.acgNodeId ? runtimeStore.value?.nodes[props.graphNode.acgNodeId] || null : null)
const safeLiveOutput = computed(() => {
  const type = props.selectedSymbol?.type
  if (type && ['agent', 'artifact', 'result', 'tool'].includes(type)) return null
  return safeStructuredOutput(liveNode.value?.outputBuffer)
})
const connectRuntime = (runId: string | null) => {
  if (props.runtimeStore) {
    releaseRunRuntimeStore(ownedRunId.value, ownedRuntimeStore.value)
    ownedRuntimeStore.value = null
    ownedRunId.value = null
    return
  }
  if (ownedRunId.value === runId) return
  releaseRunRuntimeStore(ownedRunId.value, ownedRuntimeStore.value)
  ownedRuntimeStore.value = acquireRunRuntimeStore(runId)
  ownedRunId.value = runId
}
watch([() => props.runId, () => props.runtimeStore], () => connectRuntime(props.runId))
onMounted(() => connectRuntime(props.runId))
onBeforeUnmount(() => {
  releaseRunRuntimeStore(ownedRunId.value, ownedRuntimeStore.value)
  ownedRuntimeStore.value = null
  ownedRunId.value = null
})

const emit = defineEmits<{ locateGraph: [] }>()

const inspectorContext = computed(() => ({
  ...props.workbenchContext,
  entry: props.entry,
  graphNode: props.graphNode,
  available: props.available,
  graph: props.graph,
  runStatus: props.runStatus
}) as WorkbenchInspectorContext)

const inspectorContribution = computed(() => props.registry.resolveInspector(inspectorContext.value))
const inspectorSections = computed(() => props.registry.resolveInspectorSections(inspectorContext.value))
const secondarySidebarViews = computed(() => props.registry.resolveSecondarySidebarViews(inspectorContext.value))
const inspectorTitle = computed(() => (
  props.selectedSymbol?.title
  || props.graphNode?.name
  || props.entry?.name
  || (props.entry?.kind === 'graph' ? 'graph.acg' : 'Mission')
))
const inspectorSummary = computed(() => {
  const taskLike = props.entry?.kind === 'task' || Boolean(props.graphNode)
  if (!taskLike) return null
  const status = props.graphNode?.status || props.entry?.status || props.selectedSymbol?.status || null
  const role = props.entry?.logicalRole || null
  const key = props.graphNode?.semanticTaskKey || props.entry?.semanticTaskKey || props.selectedSymbol?.semanticTaskKey || props.selectedSymbol?.subtitle || null
  const artifactCount = props.graphNode?.artifactCount ?? props.entry?.artifactCount ?? 0
  const statusTone = status && ['completed', 'succeeded'].includes(status) ? 'success'
    : status && ['failed', 'cancelled'].includes(status) ? 'danger'
      : status && ['running', 'planning', 'executing', 'pending'].includes(status) ? 'active'
        : 'muted'
  const statusLabel: Record<string, string> = {
    completed: '已完成',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
    running: '运行中',
    planning: '规划中',
    executing: '执行中',
    pending: '待执行'
  }
  return {
    role,
    status: status ? (statusLabel[status] || status) : null,
    statusTone,
    key,
    artifactCount
  }
})
const baseProps = computed(() => ({
  entry: props.entry,
  graphNode: props.graphNode,
  selectedSymbol: props.selectedSymbol || null,
  graphNodes: props.graphNodes,
  available: props.available,
  runId: props.runId,
  missionId: props.missionId,
  graph: props.graph,
  runStatus: props.runStatus,
  historical: props.historical,
  runtimeStore: runtimeStore.value,
  resourceObservation: props.workbenchContext.runtimeObservation?.resourceObservation || null,
  runtimeObservation: props.workbenchContext.runtimeObservation || null
}))
const sectionProps = (section: { getProps?: (context: WorkbenchInspectorContext) => Record<string, unknown> }) => ({
  ...baseProps.value,
  ...(section.getProps?.(inspectorContext.value) || {})
})
</script>

<style scoped>
.runtime-inspector { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; background: var(--wb-surface-pane); color: var(--wb-text); }
.runtime-inspector__empty { padding: 22px 15px; color: var(--wb-text-muted); font-size: 12px; line-height: 1.6; }
.runtime-inspector__summary { display: grid; gap: 7px; padding: 12px 15px 13px; border-bottom: 1px solid var(--wb-border-soft); background: color-mix(in srgb, var(--wb-surface-pane) 82%, var(--wb-surface-inset)); }
.runtime-inspector__summary-line { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; min-width: 0; }
.runtime-inspector__role, .runtime-inspector__status, .runtime-inspector__artifact { display: inline-flex; align-items: center; min-height: 20px; padding: 2px 7px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); font-size: 10px; line-height: 1.2; }
.runtime-inspector__role { color: var(--wb-text-secondary); background: var(--wb-surface-inset); }
.runtime-inspector__status { gap: 5px; color: var(--wb-text-secondary); }
.runtime-inspector__status i { width: 6px; height: 6px; border-radius: 50%; background: var(--wb-text-muted); }
.runtime-inspector__status.is-success { color: var(--wb-success); border-color: color-mix(in srgb, var(--wb-success) 24%, var(--wb-border-soft)); background: color-mix(in srgb, var(--wb-success) 7%, transparent); }
.runtime-inspector__status.is-success i { background: var(--wb-success); }
.runtime-inspector__status.is-danger { color: var(--wb-danger); border-color: color-mix(in srgb, var(--wb-danger) 24%, var(--wb-border-soft)); background: color-mix(in srgb, var(--wb-danger) 7%, transparent); }
.runtime-inspector__status.is-danger i { background: var(--wb-danger); }
.runtime-inspector__status.is-active { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 24%, var(--wb-border-soft)); background: color-mix(in srgb, var(--wb-accent) 7%, transparent); }
.runtime-inspector__status.is-active i { background: var(--wb-accent); }
.runtime-inspector__artifact { color: var(--wb-text-muted); }
.runtime-inspector__key { min-width: 0; overflow: hidden; color: var(--wb-text); font: 11px/1.4 var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.runtime-output { max-height: 220px; margin: 0; overflow: auto; color: var(--wb-text-secondary); font: 10px/1.5 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
