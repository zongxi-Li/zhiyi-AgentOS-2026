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
    <div v-else class="runtime-inspector__empty">选择一个 Workspace entry 或图节点查看属性。</div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AcgBlueprint, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { WorkbenchContributionRegistry } from '@/workbench/registry'
import InspectorFrame from '@/components/workbench/InspectorFrame.vue'
import SecondarySidebar from '@/components/workbench/SecondarySidebar.vue'
import type { WorkbenchContext, WorkbenchInspectorContext } from '@/workbench/types'

const props = defineProps<{
  registry: WorkbenchContributionRegistry
  workbenchContext: WorkbenchContext
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
  graphNodes: WorkspaceGraphNode[]
  available: boolean
  runId: string | null
  missionId: string
  graph: AcgBlueprint | null
  runStatus: string | null
  historical: boolean
}>()

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
  props.graphNode?.name
  || props.entry?.name
  || (props.entry?.kind === 'graph' ? 'graph.acg' : 'Mission')
))
const baseProps = computed(() => ({
  entry: props.entry,
  graphNode: props.graphNode,
  graphNodes: props.graphNodes,
  available: props.available,
  runId: props.runId,
  missionId: props.missionId,
  graph: props.graph,
  runStatus: props.runStatus,
  historical: props.historical,
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
</style>
