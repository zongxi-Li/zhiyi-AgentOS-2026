<template>
  <section class="graph-editor" aria-label="graph.acg">
    <header class="graph-editor__header">
      <div>
        <span class="graph-editor__eyebrow">GRAPH EDITOR</span>
        <strong>graph.acg</strong>
        <small v-if="graph">Graph {{ graph.graphId }} · v{{ graphVersion || '—' }}</small>
      </div>
      <span v-if="selectedSemanticTaskKey" class="graph-editor__selection">{{ selectedSemanticTaskKey }}</span>
    </header>
    <div class="graph-editor__canvas">
      <AcgTopologyGraph
        :blueprint="graph"
        :focus-node-id="focusNodeId"
        :workbench="true"
        @node-selected="handleNodeSelected"
        @node-double-clicked="handleNodeDoubleClicked"
      />
      <div v-if="!graph" class="graph-editor__empty">
        <strong>Graph unavailable</strong>
        <span>当前 Run 没有可展示的图快照。</span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AcgTopologyGraph from '@/components/agentos/AcgTopologyGraph.vue'
import type { AcgBlueprint, WorkspaceGraphNode } from '@/services/api/agentos'

const props = defineProps<{
  graph: AcgBlueprint | null
  graphNodes: WorkspaceGraphNode[]
  selectedSemanticTaskKey: string | null
  focusNodeId: string | null
}>()

const emit = defineEmits<{
  selectSemanticTask: [semanticTaskKey: string | null]
  openSemanticTask: [semanticTaskKey: string | null]
}>()

const graphVersion = computed(() => {
  const snapshot = props.graph as (AcgBlueprint & { graphVersion?: number }) | null
  return snapshot?.graphVersion || snapshot?.metadata?.graphVersion
})

const resolveSemanticKey = (nodeId: string) => props.graphNodes.find(node => node.acgNodeId === nodeId)?.semanticTaskKey || null
const handleNodeSelected = (nodeId: string) => emit('selectSemanticTask', resolveSemanticKey(nodeId))
const handleNodeDoubleClicked = (nodeId: string) => emit('openSemanticTask', resolveSemanticKey(nodeId))
</script>

<style scoped>
.graph-editor { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--bg-card); }
.graph-editor__header { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 48px; padding: 8px 16px; border-bottom: 1px solid var(--border-light); }
.graph-editor__header strong,
.graph-editor__header small { display: block; }
.graph-editor__header strong { margin-top: 2px; color: var(--text-primary); font-size: 13px; }
.graph-editor__header small { margin-top: 2px; color: var(--text-muted); font-size: 10px; }
.graph-editor__eyebrow { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.graph-editor__selection { max-width: 40%; overflow: hidden; color: var(--text-secondary); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.graph-editor__canvas { position: relative; flex: 1; min-height: 0; overflow: hidden; }
.graph-editor__canvas :deep(.acg-topology) { height: 100%; border: 0; border-radius: 0; box-shadow: none; }
.graph-editor__canvas :deep(.acg-topology .panel-head) { display: none; }
.graph-editor__canvas :deep(.acg-topology .graph-surface) { height: 100%; }
.graph-editor__canvas :deep(.acg-topology .graph-stage) { height: 100%; }
.graph-editor__empty { position: absolute; inset: 50% auto auto 50%; display: grid; gap: 5px; transform: translate(-50%, -50%); color: var(--text-secondary); text-align: center; }
.graph-editor__empty strong { color: var(--text-primary); font-size: 14px; }
.graph-editor__empty span { font-size: 12px; }
</style>
