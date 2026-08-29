<template>
  <InspectorFrame title="graph.acg" :historical="historical">
    <InspectorSection title="Graph" :badge="graphIdentity">
      <InspectorPropertyList :rows="[
        { label: 'runId', value: runId, code: true },
        { label: 'status', value: runStatus, code: true },
        { label: 'graphId', value: graph?.graphId || entry?.graphId, code: true },
        { label: 'graphVersion', value: graphVersion, code: true },
        { label: 'nodes', value: graph?.nodes.length || graphNodes.length },
        { label: 'edges', value: graph?.edges.length || 0 },
        { label: 'task plan', value: taskPlanVersion, code: true }
      ]" />
    </InspectorSection>
  </InspectorFrame>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AcgBlueprint, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import InspectorFrame from '@/components/workbench/InspectorFrame.vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{
  entry: WorkspaceEntry | null
  graphNodes: WorkspaceGraphNode[]
  runId: string | null
  graph: AcgBlueprint | null
  runStatus: string | null
  historical: boolean
}>()

const graphVersion = computed(() => {
  const graph = props.graph as (AcgBlueprint & { graphVersion?: number }) | null
  return graph?.graphVersion || graph?.metadata?.graphVersion || props.entry?.graphVersion || null
})

const taskPlanVersion = computed(() => {
  const graph = props.graph as (AcgBlueprint & { taskPlanVersion?: number }) | null
  const metadata = graph?.metadata || {}
  const value = graph?.taskPlanVersion || metadata.taskPlanVersion || metadata.plannerPlanVersion || props.entry?.metadata?.taskPlanVersion
  return value == null ? '—' : String(value)
})

const graphIdentity = computed(() => {
  if (!props.graphNodes.length) return 'unproven'
  if (props.graphNodes.every(node => node.identityQuality === 'canonical')) return 'canonical'
  if (props.graphNodes.some(node => node.identityQuality === 'legacy')) return 'mixed / legacy'
  return 'unproven'
})
</script>
