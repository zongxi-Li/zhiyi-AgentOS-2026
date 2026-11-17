<template>
  <section class="graph-editor" aria-label="graph.acg">
    <header class="graph-editor__header">
      <div class="graph-editor__title">
        <span class="graph-editor__eyebrow">GRAPH EDITOR</span>
        <strong>graph.acg</strong>
        <small v-if="displayGraph">Graph {{ displayGraph.graphId }} · v{{ graphVersion || '—' }}</small>
      </div>
      <span v-if="selectedSemanticTaskKey" class="graph-editor__selection">{{ selectedSemanticTaskKey }}</span>
    </header>
    <GraphVersionToolbar @locate-node="topology?.focusNode($event)" />
    <div v-if="!historical && executionFocus" class="graph-editor__runtime" :class="{ 'is-failed': executionFocus.blocked }" role="status">
      <span class="graph-editor__runtime-dot" aria-hidden="true" />
      <span :title="executionFocus.name">{{ executionFocus.blocked ? '执行受阻' : '当前执行' }} · {{ executionFocus.name }}</span>
      <button type="button" @click="locateExecution">{{ executionFocus.blocked ? '定位失败节点' : '定位执行中节点' }}</button>
    </div>
    <div class="graph-editor__canvas">
      <AcgTopologyGraph
        ref="topology"
        :key="versions?.selectedKey.value || 'live'"
        :blueprint="displayGraph"
        :focus-node-id="historical ? null : focusNodeId"
        :runtime-phases="runtimePhases"
        :step-states="stepStates"
        :completed-step-ids="completedStepIds"
        :run-id="historical ? null : runId"
        :historical="historical"
        :difference="versions?.difference.value"
        :workbench="true"
        :observe-resize="true"
        @node-selected="handleNodeSelected"
        @node-double-clicked="handleNodeDoubleClicked"
      />
      <div v-if="!displayGraph" class="graph-editor__empty" role="status">
        <strong>{{ versions?.snapshotLoading.value ? '正在加载图快照…' : 'Graph unavailable' }}</strong>
        <span>{{ versions?.snapshotError.value || '当前 Run 没有可展示的图快照。' }}</span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import GraphVersionToolbar from './GraphVersionToolbar.vue'
import { graphVersionsKey } from './graphVersions'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import { stepStatesFromRun } from '@/services/api/agentos/api/acg'
import AcgTopologyGraph from '@/components/agentos/AcgTopologyGraph.vue'
import type { GraphProjection, WorkspaceGraphNode } from '@/services/api/agentos'

const props = defineProps<{
  graph: GraphProjection | null
  graphNodes: WorkspaceGraphNode[]
  selectedSemanticTaskKey: string | null
  focusNodeId: string | null
  runId?: string | null
  runtimeStore?: RuntimeEventStore | null
  runtimeObservation?: RuntimeObservation | null
}>()
const versions = inject(graphVersionsKey, null)
const topology = ref<InstanceType<typeof AcgTopologyGraph> | null>(null)
const historical = computed(() => versions?.historical.value || false)
const displayGraph = computed(() => {
  const graph = versions ? versions.displayGraph.value : props.graph
  const diff = versions?.difference.value
  const before = versions?.previousGraph.value
  if (!graph || !diff || !before) return graph
  // Removed structure is visible only as a comparison overlay; it is never persisted or executed.
  return { ...graph,
    nodes: [...graph.nodes, ...before.nodes.filter(node => diff.removedNodeIds.includes(node.nodeId))],
    edges: [...graph.edges, ...before.edges.filter(edge => diff.removedEdgeIds.includes(edge.edgeId))] }
})
const runtimeMatches = computed(() => !historical.value
  && (!props.runtimeObservation || props.runtimeObservation.runId === props.runId)
  && (!props.runtimeObservation?.run?.graphVersion || props.runtimeObservation.run.graphVersion === displayGraph.value?.graphVersion))
const runtimePhases = computed(() => runtimeMatches.value && props.runtimeStore?.runId === props.runId
  ? Object.fromEntries(Object.entries(props.runtimeStore?.nodes || {}).map(([id, state]) => [id, state.phase])) : {})
// SSE 只覆盖本次连接之后的事件（无历史回放），刷新后 runtimeStore 为空。
// 图节点状态必须回落到 runtimeObservation 轮询的 run.steps 持久投影（StepStatus）。
const observedRun = computed(() => (
  runtimeMatches.value && props.runtimeObservation?.run && props.runtimeObservation.runId === props.runId
    ? props.runtimeObservation.run : null
))
const stepStates = computed(() => observedRun.value
  ? stepStatesFromRun(observedRun.value, props.runtimeObservation?.executionTree, props.runtimeObservation?.lifecycles)
  : [])
const completedStepIds = computed(() => observedRun.value?.completedStepIds || [])
const executionFocus = computed(() => {
  const run = observedRun.value
  if (!run) return null
  const visible = (id: string) => displayGraph.value?.nodes.some(node => node.nodeId === id)
  const activeId = run.activeStepIds?.find(visible)
  const failures = run.steps.filter(step => step.status === 'failed' && visible(step.stepId))
  const failedStep = failures.find(step => step.stepId === run.currentStepId) || failures[0]
  const id = activeId || failedStep?.stepId
  if (!id) return null
  const node = displayGraph.value?.nodes.find(node => node.nodeId === id)
  return { id, name: node?.name || failedStep?.name || id, blocked: !activeId }
})
const locateExecution = () => {
  const current = executionFocus.value
  if (current?.blocked) return topology.value?.focusNode(current.id)
  return topology.value?.locateCurrentTask()
}

const emit = defineEmits<{
  selectSemanticTask: [semanticTaskKey: string | null]
  openSemanticTask: [semanticTaskKey: string | null]
}>()

const graphVersion = computed(() => {
  const snapshot = displayGraph.value
  return snapshot?.graphVersion
})

const resolveSemanticKey = (nodeId: string) => props.graphNodes.find(node => node.acgNodeId === nodeId)?.semanticTaskKey || null
const isRemoved = (nodeId: string) => versions?.difference.value?.removedNodeIds.includes(nodeId)
const handleNodeSelected = (nodeId: string) => { if (!historical.value && !isRemoved(nodeId)) emit('selectSemanticTask', resolveSemanticKey(nodeId)) }
const handleNodeDoubleClicked = (nodeId: string) => { if (!historical.value && !isRemoved(nodeId)) emit('openSemanticTask', resolveSemanticKey(nodeId)) }
watch(() => versions?.selectedKey.value, () => { emit('selectSemanticTask', null) })
</script>

<style scoped>
.graph-editor { display: flex; flex: 1 1 auto; flex-direction: column; width: 100%; min-width: 0; height: 100%; min-height: 0; overflow: hidden; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-section); background: var(--wb-surface-section); color: var(--wb-text); box-shadow: var(--wb-shadow-section); }
.graph-editor__header { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 26px; padding: 3px 16px; border-bottom: 1px solid var(--wb-border-soft); background: var(--wb-surface-section); }
.graph-editor__title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.graph-editor__header strong { color: var(--wb-text); font-size: 12px; }
.graph-editor__header small { overflow: hidden; color: var(--wb-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.graph-editor__eyebrow { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.graph-editor__selection { max-width: 40%; overflow: hidden; color: var(--wb-text-secondary); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.graph-editor__runtime { --execution-color: var(--sem-running, var(--wb-accent)); display: flex; align-items: center; gap: 7px; min-height: 29px; padding: 3px 14px; border-bottom: 1px solid var(--wb-border-soft); background: color-mix(in srgb, var(--execution-color) 5%, var(--wb-surface-section)); color: var(--wb-text-secondary); font-size: 11px; }
.graph-editor__runtime.is-failed { --execution-color: var(--sem-failed, var(--wb-danger)); }
.graph-editor__runtime > span:nth-child(2) { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.graph-editor__runtime-dot { flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%; background: var(--execution-color); }
.graph-editor__runtime button { flex-shrink: 0; border: 0; padding: 4px 0 4px 8px; background: transparent; color: var(--execution-color); cursor: pointer; font: inherit; }
.graph-editor__runtime button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 2px; }
.graph-editor__canvas { position: relative; flex: 1; min-height: 0; overflow: hidden; }
.graph-editor__canvas :deep(.acg-topology) { height: 100%; border: 0; border-radius: 0; box-shadow: none; }
.graph-editor__canvas :deep(.acg-topology .panel-head) { display: none; }
.graph-editor__canvas :deep(.acg-topology .graph-surface) { height: 100%; }
.graph-editor__canvas :deep(.acg-topology .graph-stage) { height: 100%; }
.graph-editor__empty { position: absolute; inset: 50% auto auto 50%; display: grid; gap: 5px; transform: translate(-50%, -50%); color: var(--wb-text-secondary); text-align: center; }
.graph-editor__empty strong { color: var(--wb-text); font-size: 14px; }
.graph-editor__empty span { font-size: 12px; }
</style>
