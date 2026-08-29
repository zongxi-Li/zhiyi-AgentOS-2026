<template>
  <div class="sidebar-view-stack">
    <InspectorSection title="运行状态" :badge="statusLabel">
      <div class="sidebar-status">
        <span class="sidebar-status__dot" :class="`is-${statusValue || 'unobserved'}`" aria-hidden="true"></span>
        <strong>{{ statusLabel }}</strong>
      </div>
      <InspectorPropertyList :rows="[
        { label: 'Run', value: runId, code: true },
        { label: '对象', value: objectLabel },
        { label: '模式', value: historical ? 'Historical / Read-only' : 'Read-only' }
      ]" />
    </InspectorSection>

    <InspectorSection v-if="showGraphSummary" title="图信息" :badge="graphIdentity">
      <div class="sidebar-metrics" aria-label="图统计">
        <div><strong>{{ nodeCount }}</strong><span>节点</span></div>
        <div><strong>{{ edgeCount }}</strong><span>边</span></div>
        <div><strong>{{ graphVersion ?? '—' }}</strong><span>版本</span></div>
      </div>
      <InspectorPropertyList :rows="[
        { label: 'Graph ID', value: graph?.graphId || entry?.graphId, code: true },
        { label: 'Task plan', value: entry?.metadata?.taskPlanVersion == null ? '—' : String(entry.metadata.taskPlanVersion), code: true }
      ]" />
    </InspectorSection>

    <InspectorSection v-if="showTaskSummary" title="执行摘要" :badge="`${artifactCount} artifacts`">
      <div class="sidebar-metrics sidebar-metrics--two" aria-label="任务执行统计">
        <div><strong>{{ attemptCount }}</strong><span>Attempts</span></div>
        <div><strong>{{ artifactCount }}</strong><span>Artifacts</span></div>
      </div>
      <InspectorPropertyList :rows="[
        { label: 'semanticTaskKey', value: taskKey, code: true },
        { label: 'taskId', value: props.graphNode?.taskId || props.entry?.taskId, code: true },
        { label: 'status', value: statusLabel },
        { label: 'latest attempt', value: latestAttemptId, code: true }
      ]" />
    </InspectorSection>

    <InspectorSection v-if="showArtifactSummary" title="Artifact 身份" :badge="entry?.identityQuality || 'unproven'">
      <InspectorPropertyList :rows="[
        { label: 'artifactId', value: entry?.artifactId, code: true },
        { label: 'artifactKey', value: entry?.artifactKey, code: true },
        { label: 'producerAttemptId', value: entry?.attemptId, code: true },
        { label: 'semanticTaskKey', value: entry?.semanticTaskKey, code: true },
        { label: 'runId', value: entry?.runId || runId, code: true }
      ]" />
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AcgBlueprint, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
  graphNodes: WorkspaceGraphNode[]
  runId: string | null
  graph: AcgBlueprint | null
  runStatus: string | null
  historical: boolean
}>()

const statusValue = computed(() => props.graphNode?.status || props.entry?.status || props.runStatus || null)
const statusLabel = computed(() => statusValue.value || '未观测')
const objectLabel = computed(() => props.graphNode?.name || props.entry?.name || 'Mission')
const taskKey = computed(() => props.graphNode?.semanticTaskKey || props.entry?.semanticTaskKey || null)
const isArtifact = computed(() => props.entry?.kind === 'artifact')
const isTask = computed(() => props.entry?.kind === 'task')
const isGraph = computed(() => props.entry?.kind === 'graph' || props.entry?.kind === 'run' || !props.entry)
const showGraphSummary = computed(() => isGraph.value && !props.graphNode && Boolean(props.graph || props.graphNodes.length))
const showTaskSummary = computed(() => Boolean(props.graphNode || isTask.value))
const showArtifactSummary = computed(() => isArtifact.value)
const attemptCount = computed(() => props.graphNode?.attemptId ? 1 : props.entry?.attemptCount ?? 0)
const artifactCount = computed(() => props.graphNode?.artifactCount ?? props.entry?.artifactCount ?? 0)
const latestAttemptId = computed(() => props.graphNode?.attemptId || props.entry?.latestAttemptId || props.entry?.attemptId || null)
const nodeCount = computed(() => props.graph?.nodes?.length ?? props.graphNodes.length)
const edgeCount = computed(() => props.graph?.edges?.length ?? 0)
const graphVersion = computed(() => {
  const graph = props.graph as (AcgBlueprint & { graphVersion?: number }) | null
  return graph?.graphVersion ?? graph?.metadata?.graphVersion ?? props.entry?.graphVersion ?? null
})
const graphIdentity = computed(() => {
  if (!props.graphNodes.length) return 'unproven'
  if (props.graphNodes.every(node => node.identityQuality === 'canonical')) return 'canonical'
  if (props.graphNodes.some(node => node.identityQuality === 'legacy')) return 'mixed / legacy'
  return 'unproven'
})
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.sidebar-status { display: flex; align-items: center; gap: 8px; min-height: 30px; margin-bottom: 4px; color: var(--wb-text); }
.sidebar-status strong { font-size: 13px; font-weight: 650; }
.sidebar-status__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--wb-text-muted); }
.sidebar-status__dot.is-succeeded, .sidebar-status__dot.is-completed { background: var(--wb-success); }
.sidebar-status__dot.is-failed { background: var(--wb-danger); }
.sidebar-status__dot.is-running, .sidebar-status__dot.is-planning { background: var(--wb-accent); }
.sidebar-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 8px; }
.sidebar-metrics--two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.sidebar-metrics > div { display: grid; gap: 2px; min-width: 0; }
.sidebar-metrics strong { color: var(--wb-text); font: 16px var(--font-mono, monospace); }
.sidebar-metrics span { color: var(--wb-text-muted); font-size: 10px; }
</style>
