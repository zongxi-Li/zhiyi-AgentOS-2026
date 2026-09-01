<template>
  <section class="progress-editor" aria-label="运行进度">
    <header class="progress-editor__header">
      <div class="progress-editor__title">
        <span class="progress-editor__mark" aria-hidden="true">RUN</span>
        <strong>{{ runId || '未关联 Run' }}</strong>
      </div>
      <span v-if="phaseLabel" class="progress-editor__phase">{{ phaseLabel }}</span>
    </header>

    <div v-if="!runId" class="progress-editor__empty">当前 Mission 尚无可展示的 Run。</div>

    <div v-else class="progress-editor__body">
      <WorkflowProgressBar
        :progress="progressTracker.progress.value"
        :loading="progressTracker.isLoading.value"
        :sync-error="progressTracker.syncError.value"
      />

      <dl class="progress-editor__counters">
        <div v-for="counter in counters" :key="counter.label" class="progress-editor__counter">
          <dt>{{ counter.label }}</dt>
          <dd :class="counter.tone">{{ counter.value }}</dd>
        </div>
      </dl>

      <div v-if="activeTasks.length" class="progress-editor__active">
        <span class="progress-editor__section-label">进行中的步骤</span>
        <div class="progress-editor__chips">
          <button
            v-for="task in activeTasks"
            :key="task.id"
            type="button"
            class="progress-editor__chip"
            :disabled="!task.semanticTaskKey"
            :title="task.semanticTaskKey ? '打开对应任务' : undefined"
            @click="task.semanticTaskKey && emit('openSemanticTask', task.semanticTaskKey)"
          >
            {{ task.name }}
          </button>
        </div>
      </div>

      <footer class="progress-editor__meta">
        <span v-if="progressTracker.progress.value?.startedAt">开始于 {{ formatTime(progressTracker.progress.value.startedAt) }}</span>
        <span v-if="progressTracker.progress.value?.updatedAt">更新于 {{ formatTime(progressTracker.progress.value.updatedAt) }}</span>
      </footer>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import type { MissionWorkspaceProjection, WorkspaceEntry } from '@/services/api/agentos'
import { useWorkflowProgress } from '@/composables/useWorkflowProgress'
import WorkflowProgressBar from '@/components/agentos/WorkflowProgressBar.vue'

const props = defineProps<{
  entry: WorkspaceEntry
  projection: MissionWorkspaceProjection
  runId: string | null
}>()

const emit = defineEmits<{
  openSemanticTask: [semanticTaskKey: string]
}>()

const progressTracker = useWorkflowProgress()

watch(() => props.runId, runId => {
  if (runId) void progressTracker.start(runId, { fresh: true })
  else progressTracker.reset()
}, { immediate: true })

onBeforeUnmount(() => progressTracker.stop())

const PHASE_LABELS: Record<string, string> = {
  understanding: '意图理解',
  planning: '规划中',
  graph_building: '构建执行图',
  executing: '执行中',
  review: '等待评审',
  recovery: '恢复中',
  completed: '已完成',
  failed: '已失败',
  cancelled: '已取消'
}

const phaseLabel = computed(() => {
  const phase = progressTracker.progress.value?.phase
  return phase ? PHASE_LABELS[phase] || phase : null
})

const counters = computed(() => {
  const progress = progressTracker.progress.value
  return [
    { label: '总步骤', value: progress?.totalSteps ?? 0, tone: '' },
    { label: '已完成', value: progress?.completedSteps ?? 0, tone: 'is-done' },
    { label: '运行中', value: progress?.runningSteps ?? 0, tone: 'is-running' },
    { label: '待执行', value: progress?.pendingSteps ?? 0, tone: '' },
    { label: '待评审', value: progress?.waitingReviewSteps ?? 0, tone: 'is-review' },
    { label: '重试中', value: progress?.retryingSteps ?? 0, tone: 'is-review' },
    { label: '已失败', value: progress?.failedSteps ?? 0, tone: 'is-failed' },
    { label: '已取消', value: progress?.cancelledSteps ?? 0, tone: 'is-failed' }
  ]
})

const activeTasks = computed(() => {
  const activeIds = progressTracker.progress.value?.activeStepIds || []
  const nodes = props.projection.graphNodes
  return activeIds.map(id => {
    const node = nodes.find(item => item.acgNodeId === id)
    return {
      id,
      name: node?.name || id,
      semanticTaskKey: node?.semanticTaskKey || null
    }
  })
})

const formatTime = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString()
}
</script>

<style scoped>
.progress-editor { display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: auto; color: var(--wb-text); }
.progress-editor__header { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.progress-editor__title { display: flex; align-items: baseline; gap: 9px; min-width: 0; }
.progress-editor__mark { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.progress-editor__title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.progress-editor__phase { flex: 0 0 auto; padding: 3px 9px; border: 1px solid var(--wb-border); border-radius: 999px; color: var(--wb-text-secondary); font-size: 11px; }
.progress-editor__empty { display: grid; place-items: center; flex: 1; color: var(--wb-text-muted); font-size: 12px; }
.progress-editor__body { display: flex; flex-direction: column; gap: 16px; }
.progress-editor__counters { display: grid; grid-template-columns: repeat(auto-fit, minmax(86px, 1fr)); gap: 8px; margin: 0; }
.progress-editor__counter { display: grid; gap: 4px; padding: 10px 12px; border: 1px solid var(--wb-border); background: var(--wb-surface-2); }
.progress-editor__counter dt { color: var(--wb-text-muted); font-size: 10px; }
.progress-editor__counter dd { margin: 0; font: 600 16px var(--font-mono, monospace); }
.progress-editor__counter dd.is-done { color: var(--wb-accent); }
.progress-editor__counter dd.is-running { color: var(--wb-accent); }
.progress-editor__counter dd.is-review { color: var(--wb-warning); }
.progress-editor__counter dd.is-failed { color: var(--wb-danger); }
.progress-editor__section-label { color: var(--wb-text-muted); font-size: 10px; letter-spacing: .06em; }
.progress-editor__active { display: grid; gap: 8px; }
.progress-editor__chips { display: flex; flex-wrap: wrap; gap: 7px; }
.progress-editor__chip { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 5px 11px; border: 1px solid color-mix(in srgb, var(--wb-accent) 32%, var(--wb-border)); border-radius: 999px; color: var(--wb-accent); background: transparent; cursor: pointer; font-size: 11px; }
.progress-editor__chip:disabled { color: var(--wb-text-secondary); border-color: var(--wb-border); cursor: default; }
.progress-editor__chip:not(:disabled):hover { background: var(--wb-hover); }
.progress-editor__meta { display: flex; gap: 16px; color: var(--wb-text-muted); font-size: 10px; }
</style>
