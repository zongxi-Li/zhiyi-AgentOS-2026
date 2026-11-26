<template>
  <div class="planning-graph">
    <p v-if="!plan" class="planning-graph__empty" role="status">暂无可查看的规划快照。</p>
    <template v-else>
      <header class="planning-graph__summary">
        <strong>规划图 ACG · v{{ plan.planVersion }}</strong>
        <p v-if="plan.objective">{{ plan.objective }}</p>
        <p v-if="plan.constraints.length">约束：{{ plan.constraints.join('；') }}</p>
        <p v-if="plan.expectedArtifacts.length">预期交付物：{{ plan.expectedArtifacts.join('、') }}</p>
      </header>
      <section v-if="difference && previousPlan" class="planning-graph__changes" aria-label="ACG 规划变更">
        <strong>ACG v{{ previousPlan.planVersion }} → v{{ plan.planVersion }}</strong>
        <span>新增 {{ difference.addedNodeIds.length }} · 调整 {{ difference.updatedNodeIds.length }} · 移除 {{ difference.removedNodeIds.length }}</span>
        <span>依赖 +{{ difference.addedEdgeIds.length }} / ~{{ difference.updatedEdgeIds.length }} / −{{ difference.removedEdgeIds.length }}</span>
        <p v-if="!hasChanges">ACG 规划内容沿用，查看对应的 RGraph 执行展开。</p>
      </section>
      <div class="planning-graph__canvas">
        <AcgTopologyGraph v-if="blueprint" :blueprint="blueprint" :difference="difference" title="规划图 ACG" historical workbench overview-on-load
          @node-selected="selectedKey = $event" />
      </div>
      <section v-if="selectedTask" class="planning-graph__task" aria-label="规划步骤详情">
        <strong>{{ selectedTask.title }}</strong>
        <p>{{ selectedTask.objective }}</p>
        <p v-if="selectedTask.capabilities?.length">所需能力：{{ selectedTask.capabilities.join('、') }}</p>
        <p v-if="dependencies.length">依赖步骤：{{ dependencies.join('、') }}</p>
        <p v-if="selectedTask.acceptanceCriteria.length">验收条件：{{ selectedTask.acceptanceCriteria.join('；') }}</p>
        <div class="planning-graph__links">
          <span>对应 RGraph 执行节点</span>
          <button v-for="node in runtimeNodes" :key="node.nodeId" type="button" @click="emit('locate-runtime', node.nodeId)">
            {{ node.name || node.nodeId }} ↗
          </button>
          <span v-if="!runtimeNodes.length">该版本 RGraph 暂无已关联节点</span>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AcgTopologyGraph from '@/components/agentos/AcgTopologyGraph.vue'
import type { GraphProjection, WorkspaceGraphNode } from '@/services/api/agentos'
import type { CopilotInitialPlan } from '@/services/api/agentos/api/copilot'
import { planningGraph } from './planningSnapshots'
import type { GraphDifference } from '@/utils/acgGraphDifference'

const props = defineProps<{ plan: CopilotInitialPlan | null; previousPlan?: CopilotInitialPlan | null; difference?: GraphDifference | null; runId: string | null; graph: GraphProjection | null; graphNodes: WorkspaceGraphNode[]; taskKey?: string | null }>()
const emit = defineEmits<{ 'locate-runtime': [nodeId: string] }>()
const selectedKey = ref<string | null>(null)
const tasks = computed(() => new Map(props.plan?.tasks.map(task => [task.key, task])))
const selectedTask = computed(() => tasks.value.get(selectedKey.value || '') || (props.difference?.removedNodeIds.includes(selectedKey.value || '')
  ? props.previousPlan?.tasks.find(task => task.key === selectedKey.value) : undefined))
watch(() => [props.runId, props.plan?.commitId, props.plan?.planVersion, props.taskKey], (next, previous) => {
  const preferred = props.taskKey || (next[0] === previous?.[0] ? selectedKey.value : null)
  selectedKey.value = preferred && tasks.value.has(preferred) ? preferred : props.plan?.tasks[0]?.key || null
}, { immediate: true })
const relations = computed(() => (props.plan?.relations || []).filter(relation =>
  relation.relationType === 'depends_on' && tasks.value.has(relation.sourceKey) && tasks.value.has(relation.targetKey)))
const dependencies = computed(() => relations.value.filter(relation => relation.targetKey === selectedKey.value)
  .map(relation => tasks.value.get(relation.sourceKey)?.title || relation.sourceKey))
const hasChanges = computed(() => props.difference && Object.values(props.difference).some(ids => ids.length > 0))
const blueprint = computed<GraphProjection | null>(() => {
  if (!props.plan) return null
  const current = planningGraph(props.plan)
  if (!props.difference || !props.previousPlan) return current
  const before = planningGraph(props.previousPlan)
  return { ...current,
    nodes: [...current.nodes, ...before.nodes.filter(node => props.difference!.removedNodeIds.includes(node.nodeId))],
    edges: [...current.edges, ...before.edges.filter(edge => props.difference!.removedEdgeIds.includes(edge.edgeId))] }
})
const runtimeNodes = computed(() => {
  if (!selectedTask.value) return []
  const key = selectedTask.value.key
  const canonicalKeys = new Map(props.graphNodes.map(node => [node.acgNodeId, node.semanticTaskKey]))
  return (props.graph?.nodes || []).filter(node => node.nodeType === 'step'
    && (node.display?.semanticTaskKey || canonicalKeys.get(node.nodeId)) === key)
})
</script>

<style scoped>
.planning-graph { display: flex; flex: 1 1 auto; flex-direction: column; min-height: 0; width: 100%; overflow: auto; }
.planning-graph__summary, .planning-graph__task { flex: 0 0 auto; padding: 10px 14px; overflow-wrap: anywhere; font-size: 12px; }
.planning-graph__summary p, .planning-graph__task p { margin: 4px 0; color: var(--wb-text-secondary); }
.planning-graph__canvas { flex: 1 0 240px; min-height: 240px; }
.planning-graph__canvas :deep(.acg-topology) { height: 100%; }
.planning-graph__canvas :deep(.panel-head), .planning-graph__canvas :deep(.graph-toolbar) { display: none; }
.planning-graph__changes { display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 8px 14px; background: var(--wb-surface-inset); color: var(--wb-text-secondary); font-size: 11px; }
.planning-graph__changes p { width: 100%; margin: 0; }
.planning-graph__task { border-top: 1px solid var(--wb-border-soft); }
.planning-graph__links { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; margin-top: 8px; color: var(--wb-text-secondary); }
.planning-graph__links button { max-width: 100%; border: 1px solid var(--wb-border-soft); background: var(--wb-surface-section); color: var(--wb-accent); border-radius: 5px; padding: 3px 8px; overflow-wrap: anywhere; cursor: pointer; }
.planning-graph__empty { margin: auto; padding: 14px; color: var(--wb-text-secondary); }
</style>
