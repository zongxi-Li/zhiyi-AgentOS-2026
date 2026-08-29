<template>
  <aside class="runtime-inspector" aria-label="Workspace Inspector">
    <component
      v-if="inspectorContribution"
      :is="inspectorContribution.component"
      :entry="entry"
      :graph-node="graphNode"
      :graph-nodes="graphNodes"
      :available="available"
      :run-id="runId"
      :mission-id="missionId"
      :graph="graph"
      :run-status="runStatus"
      :historical="historical"
      @locate-graph="emit('locateGraph')"
    />
    <div v-else class="runtime-inspector__empty">选择一个 Workspace entry 或图节点查看属性。</div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AcgBlueprint, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { WorkbenchContributionRegistry } from '@/workbench/registry'
import type { WorkbenchContext } from '@/workbench/types'

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
}))

const inspectorContribution = computed(() => props.registry.resolveInspector(inspectorContext.value))
</script>

<style scoped>
.runtime-inspector { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; background: var(--bg-card); color: var(--text-primary); }
.runtime-inspector__empty { padding: 22px 15px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }
</style>
