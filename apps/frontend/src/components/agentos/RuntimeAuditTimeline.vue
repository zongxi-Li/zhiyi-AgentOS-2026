<template>
  <section class="runtime-audit-timeline ui-surface" aria-label="执行运行时 运行审计时间线">
    <header>
      <div><span class="eyebrow">Execution Audit</span><strong>运行审计时间线</strong></div>
      <span>{{ items.length }} 条</span>
    </header>
    <p v-if="!items.length" class="empty">尚无 Trace、恢复、Checkpoint、Review 或 GraphPatch 引用</p>
    <ol v-else>
      <li v-for="item in items" :key="item.id" :class="`kind-${item.kind}`">
        <span class="marker" aria-hidden="true"></span>
        <div class="content">
          <div class="item-head">
            <strong>{{ item.title }}</strong>
            <time v-if="item.time">{{ formatTime(item.time) }}</time>
          </div>
          <p>{{ item.description }}</p>
          <div v-if="item.meta.length" class="meta">
            <code v-for="value in item.meta" :key="value">{{ value }}</code>
          </div>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Checkpoint, ReviewRecord, TraceEvent } from '@/services/api/workflow'

type AuditKind = 'trace' | 'patch' | 'recovery' | 'checkpoint' | 'review' | 'communication'
interface AuditItem {
  id: string
  kind: AuditKind
  title: string
  description: string
  time?: string
  meta: string[]
  order: number
}

const props = withDefaults(defineProps<{
  events?: TraceEvent[]
  patchRefs?: string[]
  checkpoints?: Checkpoint[]
  reviews?: ReviewRecord[]
  maxItems?: number
}>(), {
  events: () => [],
  patchRefs: () => [],
  checkpoints: () => [],
  reviews: () => [],
  maxItems: 12
})

const eventLabels: Record<string, string> = {
  RUN_STARTED: '运行开始',
  RUN_COMPLETED: '运行完成',
  RUN_FAILED: '运行失败',
  RUN_RECOVERED: '运行恢复',
  RUN_DEGRADED: '降级交付记录',
  STEP_STARTED: '步骤开始',
  STEP_COMPLETED: '步骤完成',
  STEP_FAILED: '步骤失败',
  STEP_RETRYING: '步骤重试',
  STEP_SKIPPED_BY_CONDITION: '条件跳过',
  CHECKPOINT_CREATED: 'Checkpoint 已创建',
  REVIEW_REQUIRED: '等待人工审核',
  REVIEW_DECIDED: '审核决定已提交',
  GRAPH_PATCH_APPLIED: 'GraphPatch 已应用',
  MODEL_BINDING_CHANGED: '执行绑定已切换',
  COMMUNICATION_RECORDED: '低熵通信已记录'
}
const eventLabel = (type: string) => eventLabels[type.toUpperCase()] || type.replace(/_/g, ' ')

const kindOf = (type: string): AuditKind => {
  const normalized = type.toUpperCase()
  if (normalized.includes('PATCH')) return 'patch'
  if (normalized.includes('RECOVER') || normalized.includes('RETRY') || normalized.includes('DEGRADED')) return 'recovery'
  if (normalized.includes('CHECKPOINT')) return 'checkpoint'
  if (normalized.includes('REVIEW')) return 'review'
  if (normalized.includes('COMMUNICATION') || normalized.includes('PROVENANCE')) return 'communication'
  return 'trace'
}

const payloadText = (event: TraceEvent): string => {
  const payload = event.payload || {}
  for (const key of ['message', 'summary', 'reason', 'reasonCode']) {
    const value = payload[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return event.observation?.trim() || `${eventLabel(event.eventType)}已写入不可变 Trace。`
}

const eventMeta = (event: TraceEvent): string[] => {
  const values = []
  if (event.stepId) values.push(`step ${event.stepId}`)
  if (event.agentName) values.push(`agent ${event.agentName}`)
  const graphVersion = event.payload?.graphVersion ?? event.payload?.graph_version
  if (typeof graphVersion === 'number' || typeof graphVersion === 'string') values.push(`graph v${graphVersion}`)
  return values
}

const timeOrder = (value?: string) => {
  const parsed = value ? Date.parse(value) : Number.NaN
  return Number.isFinite(parsed) ? parsed : 0
}

const items = computed<AuditItem[]>(() => {
  const result: AuditItem[] = props.events.map((event, index) => ({
    id: event.eventId || `trace-${index}`,
    kind: kindOf(event.eventType),
    title: eventLabel(event.eventType),
    description: payloadText(event),
    time: event.createdAt,
    meta: eventMeta(event),
    order: timeOrder(event.createdAt)
  }))
  const existing = new Set(result.map(item => item.id))
  props.patchRefs.forEach((reference, index) => {
    if (existing.has(reference)) return
    result.push({ id: reference, kind: 'patch', title: 'GraphPatch 引用', description: '受控图变更引用已登记，可通过运行详情继续追溯。', meta: [`ref ${reference}`], order: -10 - index })
  })
  props.checkpoints.forEach((checkpoint, index) => {
    if (existing.has(checkpoint.checkpointId)) return
    result.push({ id: checkpoint.checkpointId, kind: 'checkpoint', title: 'Checkpoint', description: checkpoint.canResume ? '可恢复检查点已持久化。' : '审计检查点已持久化，当前不可直接恢复。', meta: [`version ${checkpoint.version}`, `ref ${checkpoint.checkpointId}`], order: -100 - index })
  })
  props.reviews.forEach((review, index) => {
    if (existing.has(review.reviewId)) return
    result.push({ id: review.reviewId, kind: 'review', title: '人工审核', description: `步骤 ${review.stepId} 的审核决定：${review.decision}。`, time: review.createdAt, meta: [`review ${review.reviewId}`], order: timeOrder(review.createdAt) || -200 - index })
  })
  return result
    .sort((left, right) => right.order - left.order)
    .slice(0, Math.max(1, props.maxItems))
})

const formatTime = (value: string) => {
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString('zh-CN', { hour12: false }) : value
}
</script>

<style scoped>
.runtime-audit-timeline { padding: 14px; }
header, header > div, .item-head, .meta { display: flex; align-items: center; }
header { justify-content: space-between; gap: 12px; }
header > div { gap: 9px; }
header > span, .eyebrow, time, .meta { color: var(--text-secondary); font-size: 11px; }
header strong { color: var(--text-primary); font-size: 13px; }
.eyebrow { letter-spacing: .04em; text-transform: uppercase; }
.empty { margin: 14px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; text-wrap: pretty; }
ol { margin: 14px 0 0; padding: 0; list-style: none; }
li { position: relative; display: grid; grid-template-columns: 13px minmax(0, 1fr); gap: 9px; padding-bottom: 14px; }
li:not(:last-child)::before { content: ''; position: absolute; left: 5px; top: 13px; bottom: 0; width: 1px; background: var(--border-light); }
.marker { position: relative; z-index: 1; width: 9px; height: 9px; margin-top: 4px; border: 2px solid var(--bg-card); border-radius: 50%; background: var(--text-muted); box-shadow: 0 0 0 1px var(--border-light); }
.kind-patch .marker { background: var(--primary-color); }
.kind-recovery .marker { background: var(--warning); }
.kind-checkpoint .marker { background: var(--info); }
.kind-review .marker { background: var(--success); }
.kind-communication .marker { background: var(--accent-color); }
.content { min-width: 0; }
.item-head { justify-content: space-between; gap: 8px; }
.item-head strong { color: var(--text-primary); font-size: 12px; }
.content p { margin: 4px 0 6px; color: var(--text-regular); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; text-wrap: pretty; }
.meta { flex-wrap: wrap; gap: 6px 10px; }
.meta code { max-width: 100%; color: var(--primary-color); overflow-wrap: anywhere; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; }
}
</style>
