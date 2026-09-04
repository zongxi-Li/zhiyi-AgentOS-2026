<template>
  <section class="run-progress" aria-label="运行进度">
    <header class="run-progress__header">
      <h1 class="run-progress__goal">{{ goalText }}</h1>
      <div class="run-progress__meta">
        <span class="run-progress__status" :class="'is-' + runState">
          {{ stateLabel }}<template v-if="durationText"> · {{ durationText }}</template>
        </span>
        <span v-if="resolvedRunId" class="run-progress__runid">{{ resolvedRunId }}</span>
      </div>
    </header>

    <div v-if="!resolvedRunId" class="run-progress__empty">运行开始后，这里会显示任务规划和执行过程。</div>

    <template v-else>
      <nav class="run-progress__filters" aria-label="进度过滤">
        <button
          v-for="option in FILTERS"
          :key="option"
          type="button"
          class="run-progress__filter"
          :class="{ 'is-active': filter === option }"
          @click="filter = option"
        >{{ option }}</button>
      </nav>

      <div ref="scrollBody" class="run-progress__body" @scroll="onScroll">
        <div class="run-progress__stream">
          <section
            v-if="showPlanner && displayPlanner"
            class="run-progress-group"
            :class="{ 'is-open': plannerOpen }"
          >
            <button type="button" class="run-progress-group__head" @click="toggleExpanded('planner', displayPlanner.status)">
              <span class="run-progress-group__mark" :class="'is-' + displayPlanner.status" aria-hidden="true">{{ statusMark(displayPlanner.status) }}</span>
              <span class="run-progress-group__title">{{ displayPlanner.headline }}</span>
              <span v-if="!plannerOpen" class="run-progress-group__digest">{{ plannerDigest }}</span>
            </button>
            <div v-if="plannerOpen" class="run-progress-group__body">
              <p v-if="displayPlanner.status !== 'success' && displayPlanner.phaseNotes.length" class="run-progress-group__note" :class="{ 'is-failed': displayPlanner.status === 'failed' }">
                {{ displayPlanner.phaseNotes[0] }}<template v-if="plannerBudgetText"> · {{ plannerBudgetText }}</template>
              </p>
              <div v-if="livePlanning && livePlanning.status !== 'IDLE'" class="run-progress-live" aria-live="polite">
                <div class="run-progress-live__line">
                  <span class="run-progress-live__pulse" :class="{ 'is-done': livePlanning.status === 'COMPLETED', 'is-failed': livePlanning.status === 'FAILED' }" aria-hidden="true">●</span>
                  <strong>{{ plannerStageLabel }}</strong>
                  <span>{{ livePlannerModelLabel }}</span>
                  <span v-if="livePlanning.elapsedMs != null" class="run-progress-live__metric">{{ livePlanning.elapsedMs }} ms</span>
                </div>
                <div class="run-progress-live__metrics">
                  <span v-if="livePlanning.ttftMs != null">TTFT {{ livePlanning.ttftMs }} ms</span>
                  <span v-if="livePlanning.idleMs != null">Idle {{ livePlanning.idleMs }} ms</span>
                  <span v-if="livePlanning.callKey">Call {{ livePlanning.callKey }}</span>
                </div>
                <div v-if="livePlanning.profile" class="run-progress-live__facts">
                  Profile: {{ livePlanning.profile.requiredCapabilityCount ?? 0 }} capabilities · {{ livePlanning.profile.expectedArtifactCount ?? 0 }} artifacts
                </div>
                <div v-if="livePlanning.plan" class="run-progress-live__facts">
                  Plan: {{ livePlanning.plan.taskCount ?? 0 }} tasks · {{ livePlanning.plan.dependencyCount ?? 0 }} dependencies
                </div>
                <div v-if="livePlanning.graph" class="run-progress-live__facts">
                  Graph: {{ livePlanning.graph.nodeCount ?? 0 }} nodes · {{ livePlanning.graph.edgeCount ?? 0 }} edges
                </div>
                <div v-if="livePlanning.errorCode" class="run-progress-live__facts is-failed">{{ livePlanning.errorCode }}</div>
              </div>
              <div
                v-for="result in displayPlanner.results"
                :key="result.id"
                class="run-progress-result"
              >
                <span class="run-progress-result__mark" aria-hidden="true">✓</span>
                <span class="run-progress-result__title">{{ result.title }}</span>
                <span class="run-progress-result__metrics">{{ metricsText(result.metrics) }}</span>
                <button
                  v-if="result.kind === 'graph_compiled'"
                  type="button"
                  class="run-progress-result__action"
                  @click="openGraph"
                >查看 Graph</button>
              </div>
            </div>
          </section>

          <template v-if="showTasks">
            <section
              v-for="group in visibleTasks"
              :key="group.graphNodeId || group.title"
              class="run-progress-group"
              :class="{ 'is-open': isExpanded(groupKey(group), group.status) }"
            >
              <button type="button" class="run-progress-group__head" @click="toggleExpanded(groupKey(group), group.status)">
                <span class="run-progress-group__mark" :class="'is-' + group.status" aria-hidden="true">{{ statusMark(group.status) }}</span>
                <span class="run-progress-group__title">{{ group.title }}</span>
                <span v-if="!isExpanded(groupKey(group), group.status)" class="run-progress-group__digest">{{ taskDigest(group) }}</span>
              </button>
              <div v-if="isExpanded(groupKey(group), group.status)" class="run-progress-group__body">
                <p v-if="group.status === 'running'" class="run-progress-group__note">正在执行</p>
                <p v-if="group.errorCode" class="run-progress-group__note is-failed">执行失败 · {{ group.errorCode }}</p>
                <div v-for="tool in group.tools" :key="tool.id" class="run-progress-tool">
                  <span class="run-progress-tool__mark" :class="'is-' + tool.status" aria-hidden="true">{{ tool.status === 'failed' ? '×' : '↳' }}</span>
                  <span class="run-progress-tool__name">{{ tool.title }}</span>
                  <span v-if="tool.metrics.latencyMs != null" class="run-progress-tool__meta">{{ tool.metrics.latencyMs }} ms</span>
                </div>
                <div v-for="artifact in taskArtifacts(group)" :key="artifact.entryId" class="run-progress-artifact">
                  <span class="run-progress-artifact__mark" aria-hidden="true">▣</span>
                  <button type="button" class="run-progress-artifact__open" @click="emit('openArtifact', artifact)">{{ artifact.name }}</button>
                </div>
              </div>
            </section>
          </template>

          <template v-if="filter === 'Tools'">
            <div v-for="tool in flatTools" :key="tool.id" class="run-progress-tool">
              <span class="run-progress-tool__mark" :class="'is-' + tool.status" aria-hidden="true">{{ tool.status === 'failed' ? '×' : '↳' }}</span>
              <span class="run-progress-tool__name">{{ tool.title }}</span>
              <span v-if="tool.metrics.latencyMs != null" class="run-progress-tool__meta">{{ tool.metrics.latencyMs }} ms</span>
            </div>
          </template>

          <p v-if="!displayPlanner && !timeline.tasks.length" class="run-progress__waiting">
            {{ runState === 'running' ? '等待规划事件…' : runState === 'unknown' ? '暂未观测到该运行状态。' : '该运行没有可展示的事件。' }}
          </p>
        </div>

        <button
          v-if="!followLatest"
          type="button"
          class="run-progress__follow"
          @click="scrollToLatest"
        >↓ 跟随最新运行</button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { MissionWorkspaceProjection, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'
import { projectRunProgress, type RunProgressMetrics, type RunProgressPlannerGroup, type RunProgressTaskGroup } from '@/workbench/runtime/runProgress'

const props = defineProps<{
  entry: WorkspaceEntry
  projection: MissionWorkspaceProjection
  graphNodes: WorkspaceGraphNode[]
  runId: string | null
  selectedSemanticTaskKey?: string | null
  runtimeObservation: RuntimeObservation | null
  runtimeStore?: RuntimeEventStore | null
}>()

const emit = defineEmits<{
  selectSemanticTask: [semanticTaskKey: string | null]
  locateGraph: [entry: WorkspaceEntry]
  openArtifact: [entry: WorkspaceEntry]
}>()

const FILTERS = ['All', 'Tasks', 'Tools'] as const
type ProgressFilter = typeof FILTERS[number]
const filter = ref<ProgressFilter>('All')

const resolvedRunId = computed(() => props.runId || (props.entry.kind === 'run' ? props.entry.runId || null : null))
const observedRun = computed(() => props.projection.runs.find(item => item.runId === resolvedRunId.value) || null)
const runStatus = computed(() => (
  props.runtimeObservation?.runId === resolvedRunId.value
    ? props.runtimeObservation.runStatus
    : observedRun.value?.status || props.runtimeObservation?.runStatus || null
))

const TERMINAL_OK = new Set(['completed', 'succeeded'])
const TERMINAL_BAD = new Set(['failed', 'cancelled'])
const runState = computed<'idle' | 'unknown' | 'running' | 'completed' | 'failed' | 'paused'>(() => {
  if (!resolvedRunId.value) return 'idle'
  const status = runStatus.value
  if (!status) return 'unknown'
  if (status && TERMINAL_OK.has(status)) return 'completed'
  if (status && TERMINAL_BAD.has(status)) return 'failed'
  if (status === 'waiting_review') return 'paused'
  if (['queued', 'starting', 'running', 'executing', 'planning'].includes(status)) return 'running'
  return 'unknown'
})

const STATE_LABELS: Record<string, string> = {
  idle: '尚未运行',
  running: 'RUNNING',
  completed: '运行完成',
  failed: '运行失败',
  paused: '等待审核',
  unknown: '状态未知'
}
const stateLabel = computed(() => {
  const planningStatus = props.runtimeStore?.planning.status
  return planningStatus && ['STARTING', 'RUNNING'].includes(planningStatus)
    ? 'PLANNING'
    : (STATE_LABELS[runState.value] || '状态未知')
})

const nowTick = ref(0)
let durationTimer: ReturnType<typeof setInterval> | null = null
watch(runState, state => {
  if (state === 'running' && durationTimer === null) {
    durationTimer = setInterval(() => { nowTick.value += 1 }, 1000)
  } else if (state !== 'running' && durationTimer !== null) {
    clearInterval(durationTimer)
    durationTimer = null
  }
}, { immediate: true })
onBeforeUnmount(() => { if (durationTimer !== null) clearInterval(durationTimer) })

const formatDuration = (ms: number) => {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return minutes ? `${minutes}m ${String(seconds).padStart(2, '0')}s` : `${seconds}s`
}
const durationText = computed(() => {
  void nowTick.value
  const liveElapsed = props.runtimeStore?.planning.elapsedMs
  const planningStatus = props.runtimeStore?.planning.status
  if (planningStatus && ['STARTING', 'RUNNING'].includes(planningStatus) && liveElapsed != null) return formatDuration(liveElapsed)
  const start = observedRun.value?.createdAt
  if (!start) return null
  const startedAt = new Date(start).getTime()
  if (Number.isNaN(startedAt)) return null
  const finishedAt = observedRun.value?.completedAt
  const end = finishedAt && !Number.isNaN(new Date(finishedAt).getTime())
    ? new Date(finishedAt).getTime()
    : Date.now()
  return formatDuration(end - startedAt)
})

const goalText = computed(() => props.projection.mission.goal || props.projection.mission.description || '运行进度')

const timeline = computed(() => projectRunProgress(props.runtimeObservation, props.graphNodes))
const livePlanning = computed(() => props.runtimeStore?.planning || null)
const livePlannerGroup = computed<RunProgressPlannerGroup | null>(() => {
  const planning = livePlanning.value
  if (!planning || planning.status === 'IDLE') return null
  const status: RunProgressPlannerGroup['status'] = planning.status === 'FAILED'
    ? 'failed'
    : planning.status === 'COMPLETED' ? 'success' : 'running'
  return {
    category: 'planner',
    status,
    headline: status === 'failed' ? '规划失败' : '任务规划',
    phaseNotes: [planning.stage || '正在准备规划'],
    phaseBudgetSeconds: null,
    results: [],
  }
})
const displayPlanner = computed(() => timeline.value.planner || livePlannerGroup.value)
const livePlanningActive = computed(() => Boolean(
  livePlanning.value && ['STARTING', 'RUNNING'].includes(livePlanning.value.status)
))
const plannerStageLabel = computed(() => {
  const stage = livePlanning.value?.stage || ''
  const labels: Record<string, string> = {
    intent_profile: '解析任务意图',
    outline: '生成任务骨架',
    detail: '补全任务细节',
    relations: '整理依赖关系',
    decompose: '拆解执行任务',
    repair: '修复规划结构',
    repair_coverage: '补全引用覆盖',
  }
  return labels[stage] || stage || '准备规划'
})
const livePlannerModelLabel = computed(() => {
  const phase = livePlanning.value?.modelPhase
  if (phase === 'WAITING_FIRST_TOKEN') return '等待模型首 token'
  if (phase === 'ACTIVE') return '模型响应中'
  if (phase === 'COMPLETED') return '模型响应完成'
  return '启动模型调用'
})

// ---- Collapse：手动展开状态优先于运行状态，polling 不覆盖用户选择 ----
const manualExpanded = ref(new Map<string, boolean>())
const groupKey = (group: RunProgressTaskGroup) => group.graphNodeId || group.title
const AUTO_OPEN = new Set(['running', 'warning', 'failed'])
const isExpanded = (key: string, status: string) => (
  manualExpanded.value.get(key) ?? AUTO_OPEN.has(status)
)
const toggleExpanded = (key: string, status: string) => {
  const effective = manualExpanded.value.get(key) ?? AUTO_OPEN.has(status)
  const next = new Map(manualExpanded.value)
  next.set(key, !effective)
  manualExpanded.value = next
}
const plannerOpen = computed(() => {
  const planner = displayPlanner.value
  if (!planner) return false
  return manualExpanded.value.get('planner') ?? AUTO_OPEN.has(planner.status)
})
const plannerBudgetText = computed(() => {
  const planner = displayPlanner.value
  if (!planner || planner.status !== 'running' || planner.phaseBudgetSeconds == null) return null
  const minutes = Math.max(1, Math.round(planner.phaseBudgetSeconds / 60))
  return `模型推理中，预算最长 ${minutes} 分钟`
})
const plannerDigest = computed(() => {
  const planner = displayPlanner.value
  if (!planner) return ''
  if (planner.status === 'failed') return planner.phaseNotes[0] || ''
  return planner.results.map(result => [result.title, metricsText(result.metrics)].filter(Boolean).join(' · ')).join(' / ')
})
const taskDigest = (group: RunProgressTaskGroup) => {
  if (group.status === 'failed') return group.errorCode || '执行失败'
  if (group.durationMs != null) return formatDuration(group.durationMs)
  return '正在执行'
}

const statusMark = (status: string) => (
  status === 'running' ? '●' : status === 'success' ? '✓' : status === 'failed' ? '×' : '!'
)

const metricsText = (metrics: RunProgressMetrics) => {
  const parts: string[] = []
  if (metrics.taskCount != null) parts.push(`${metrics.taskCount} Tasks`)
  if (metrics.dependencyCount != null) parts.push(`${metrics.dependencyCount} Dependencies`)
  if (metrics.nodeCount != null) parts.push(`${metrics.nodeCount} Nodes`)
  if (metrics.edgeCount != null) parts.push(`${metrics.edgeCount} Edges`)
  if (metrics.constraintCount != null) parts.push(`${metrics.constraintCount} Constraints`)
  return parts.join(' · ')
}

const showPlanner = computed(() => filter.value !== 'Tools')
const showTasks = computed(() => filter.value !== 'Tools')
const visibleTasks = computed(() => {
  if (filter.value === 'Tools') return []
  const tasks = timeline.value.tasks
  return [...tasks].sort((left, right) => {
    const rank = (status: string) => (status === 'running' ? 0 : status === 'failed' ? 1 : 2)
    return rank(left.status) - rank(right.status)
  })
})
const flatTools = computed(() => timeline.value.tasks.flatMap(group => group.tools))
const taskArtifacts = (group: RunProgressTaskGroup) => (
  group.semanticTaskKey
    ? props.projection.entries.filter(entry => entry.kind === 'artifact' && entry.semanticTaskKey === group.semanticTaskKey)
    : []
)

// ---- Task / Graph 联动：更新 selection 不切换当前 editor ----
watch(() => timeline.value.tasks, tasks => {
  const running = tasks.find(group => group.status === 'running' && group.semanticTaskKey)
  const first = tasks.find(group => group.semanticTaskKey)
  const key = running?.semanticTaskKey || first?.semanticTaskKey || null
  if (key && key !== props.selectedSemanticTaskKey) emit('selectSemanticTask', key)
}, { immediate: true })

const openGraph = () => {
  const graphEntry = props.projection.entries.find(entry => entry.kind === 'graph')
  if (graphEntry) emit('locateGraph', graphEntry)
}

// ---- Follow Latest：用户上滚即停止跟随，按钮恢复 ----
const scrollBody = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const onScroll = () => {
  const el = scrollBody.value
  if (!el) return
  followLatest.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}
const scrollToLatest = async () => {
  followLatest.value = true
  await nextTick()
  const el = scrollBody.value
  if (el) el.scrollTop = el.scrollHeight
}
watch(timeline, async () => {
  if (!followLatest.value) return
  await nextTick()
  const el = scrollBody.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<style scoped>
.run-progress { display: flex; flex-direction: column; height: 100%; min-height: 0; color: var(--wb-text); }
.run-progress__header { display: grid; gap: 5px; max-width: 920px; padding-bottom: 12px; border-bottom: 1px solid var(--wb-border-soft); }
.run-progress__goal { margin: 0; font-size: 15px; font-weight: 600; line-height: 1.45; }
.run-progress__meta { display: flex; align-items: baseline; gap: 12px; }
.run-progress__status { font: 10px var(--font-mono, monospace); letter-spacing: .08em; color: var(--wb-accent); }
.run-progress__status.is-completed { color: var(--wb-success); }
.run-progress__status.is-failed { color: var(--wb-danger); }
.run-progress__status.is-paused { color: var(--wb-warning); }
.run-progress__runid { overflow: hidden; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.run-progress__empty { display: grid; flex: 1; place-items: center; color: var(--wb-text-muted); font-size: 12px; }
.run-progress__filters { display: flex; gap: 2px; padding: 8px 0; }
.run-progress__filter { padding: 3px 10px; border: 0; border-radius: 999px; color: var(--wb-text-muted); background: transparent; cursor: pointer; font-size: 11px; transition: color 140ms var(--ease-out), background-color 140ms var(--ease-out); }
.run-progress__filter.is-active { color: var(--wb-text); background: var(--wb-hover); }
.run-progress__body { position: relative; flex: 1; min-height: 0; overflow: auto; scrollbar-width: thin; scrollbar-color: var(--wb-border-strong) transparent; }
.run-progress__stream { max-width: 880px; padding-bottom: 42px; }
.run-progress__waiting { padding: 16px 2px; color: var(--wb-text-muted); font-size: 12px; }
.run-progress-group { padding: 4px 0; }
.run-progress-group__head { display: flex; align-items: baseline; gap: 9px; width: 100%; padding: 6px 2px; border: 0; background: transparent; cursor: pointer; text-align: left; }
.run-progress-group__mark { flex: 0 0 auto; font-size: 11px; }
.run-progress-group__mark.is-running { color: var(--wb-accent); }
.run-progress-group__mark.is-success { color: var(--wb-success); }
.run-progress-group__mark.is-warning { color: var(--wb-warning); }
.run-progress-group__mark.is-failed { color: var(--wb-danger); }
.run-progress-group__title { color: var(--wb-text); font-size: 12.5px; font-weight: 600; }
.run-progress-group__digest { overflow: hidden; color: var(--wb-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.run-progress-group__body { display: grid; gap: 6px; padding: 2px 0 8px 22px; }
.run-progress-group__note { margin: 0; color: var(--wb-text-secondary); font-size: 11.5px; }
.run-progress-group__note.is-failed { color: var(--wb-danger); }
.run-progress-live { display: grid; gap: 5px; padding: 7px 9px; border-left: 2px solid var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 7%, transparent); }
.run-progress-live__line, .run-progress-live__metrics { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; color: var(--wb-text-secondary); font-size: 11px; }
.run-progress-live__line strong { color: var(--wb-text); font-size: 11.5px; }
.run-progress-live__metric, .run-progress-live__metrics, .run-progress-live__facts { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.run-progress-live__pulse { color: var(--wb-accent); }
.run-progress-live__pulse.is-done { color: var(--wb-success); }
.run-progress-live__pulse.is-failed, .run-progress-live__facts.is-failed { color: var(--wb-danger); }
.run-progress-live__facts { line-height: 1.5; }
.run-progress-result { display: flex; align-items: baseline; gap: 8px; }
.run-progress-result__mark { color: var(--wb-success); font-size: 11px; }
.run-progress-result__title { color: var(--wb-text); font-size: 12px; }
.run-progress-result__metrics { color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); }
.run-progress-result__action { padding: 1px 8px; border: 1px solid color-mix(in srgb, var(--wb-accent) 32%, var(--wb-border)); border-radius: 999px; color: var(--wb-accent); background: transparent; cursor: pointer; font-size: 10px; }
.run-progress-result__action:hover { border-color: color-mix(in srgb, var(--wb-accent) 58%, var(--wb-border)); background: var(--wb-hover); }
.run-progress-tool { display: flex; align-items: baseline; gap: 8px; }
.run-progress-tool__mark { flex: 0 0 auto; color: var(--wb-text-muted); font-size: 11px; }
.run-progress-tool__mark.is-failed { color: var(--wb-danger); }
.run-progress-tool__name { color: var(--wb-text-secondary); font-size: 11.5px; }
.run-progress-tool__meta { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.run-progress-artifact { display: flex; align-items: baseline; gap: 8px; }
.run-progress-artifact__mark { color: var(--wb-accent); font-size: 11px; }
.run-progress-artifact__open { padding: 0; border: 0; color: var(--wb-accent); background: transparent; cursor: pointer; font-size: 11.5px; }
.run-progress-artifact__open:hover { text-decoration: underline; }
.run-progress__follow { position: sticky; bottom: 10px; display: block; margin: 0 auto; padding: 5px 14px; border: 1px solid color-mix(in srgb, var(--wb-accent) 34%, var(--wb-border)); border-radius: 999px; color: var(--wb-accent); background: var(--wb-surface-2); cursor: pointer; font-size: 11px; box-shadow: 0 2px 8px rgba(0, 0, 0, .18); }
</style>
