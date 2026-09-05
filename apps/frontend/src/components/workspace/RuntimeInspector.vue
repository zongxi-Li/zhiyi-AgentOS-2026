<template>
  <aside class="runtime-inspector" aria-label="Selection Inspector">
    <InspectorFrame v-if="inspectorContribution || inspectorSections.length" :title="inspectorTitle" :historical="historical">
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
const inspectorTitle = computed(() => (
  props.selectedSymbol?.title
  || props.graphNode?.name
  || props.entry?.name
  || (props.entry?.kind === 'graph' ? 'graph.acg' : 'Mission')
))
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
.runtime-output { max-height: 220px; margin: 0; overflow: auto; color: var(--wb-text-secondary); font: 10px/1.5 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
