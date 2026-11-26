<template>
  <div v-if="snapshots.loading.value || snapshots.error.value" class="planning-state" role="status">
    <span>{{ snapshots.error.value || '正在读取 ACG 规划版本…' }}</span>
    <button v-if="snapshots.error.value" type="button" @click="snapshots.refresh()">重试</button>
  </div>
  <PlanningGraphView v-else :plan="snapshots.plan.value" :previous-plan="snapshots.previous.value"
    :difference="snapshots.difference.value" :run-id="runId" :graph="graph"
    :graph-nodes="[]" :task-key="taskKey"
    @locate-runtime="emit('locate-runtime', $event)" />
</template>

<script setup lang="ts">
import { computed, inject } from 'vue'
import type { GraphProjection, WorkspaceGraphNode } from '@/services/api/agentos'
import PlanningGraphView from './PlanningGraphView.vue'
import { graphVersionsKey } from './graphVersions'
import { usePlanningSnapshots } from './planningSnapshots'

const props = defineProps<{ runId: string | null; graph: GraphProjection | null; graphNodes: WorkspaceGraphNode[]; taskKey?: string | null; initialPlanVersion?: number | null }>()
const emit = defineEmits<{ 'locate-runtime': [nodeId: string] }>()
const versions = inject(graphVersionsKey, null)
const historical = computed(() => versions?.historical.value
  || Boolean(versions && !versions.following.value && !versions.selected.value))
const snapshots = usePlanningSnapshots({
  runId: computed(() => props.runId),
  planVersion: computed(() => versions && !versions.following.value && !versions.selected.value ? null
    : versions?.selected.value ? versions.selected.value.taskPlanVersion ?? null
    : props.graph?.taskPlanVersion ?? (!props.graph ? props.initialPlanVersion ?? null : null)),
  previousVersion: computed(() => versions?.previous.value?.taskPlanVersion ?? null),
  identity: computed(() => versions?.selectedKey.value || JSON.stringify([props.graph?.graphId, props.graph?.graphVersion, props.initialPlanVersion])),
  enabled: computed(() => true), historical,
  comparing: computed(() => versions?.comparing.value || false),
})
</script>

<style scoped>
.planning-state { display: flex; align-items: center; justify-content: center; flex: 1; gap: 10px; padding: 16px; color: var(--wb-text-secondary); font-size: 12px; }
.planning-state button { border: 0; background: transparent; color: var(--wb-accent); cursor: pointer; font: inherit; }
</style>
