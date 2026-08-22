<template>
  <section class="identity-health" :class="health?.status || 'unknown'" aria-label="Identity 投影健康度">
    <div class="health-title">
      <el-icon><CircleCheck v-if="health?.status === 'healthy'" /><Warning v-else /></el-icon>
      <div><strong>Identity 投影</strong><span>{{ statusLabel }}</span></div>
    </div>
    <div v-if="health" class="health-metrics">
      <span><small>Backlog</small><b>{{ health.backlogCount }}</b></span>
      <span><small>失败</small><b>{{ health.failedCount }}</b></span>
      <span><small>Inbox</small><b>{{ health.inboxBacklog }}</b></span>
      <span><small>Outbox</small><b>{{ health.outboxBacklog }}</b></span>
      <span><small>未应用</small><b>{{ health.unappliedEventCount }}</b></span>
      <span><small>已检查</small><b>{{ examinedCount }}</b></span>
      <span><small>已修复</small><b>{{ repairedCount }}</b></span>
      <span><small>已重放</small><b>{{ health.startupReconciliation.replayedEvents }}</b></span>
    </div>
    <div class="health-meta">
      <span v-if="health?.oldestEventAt">最早事件 {{ formatTime(health.oldestEventAt) }}</span>
      <span v-if="lastUpdatedAt">更新于 {{ formatTime(lastUpdatedAt) }}</span>
      <span v-if="loading">同步中</span>
      <span v-if="error" class="stale">{{ error }} · 保留上次结果</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Warning } from '@element-plus/icons-vue'
import type { IdentityProjectionHealth } from '@/services/api/workflow'

const props = defineProps<{
  health: IdentityProjectionHealth | null
  loading: boolean
  error: string
  lastUpdatedAt: string | null
}>()
const statusLabel = computed(() => props.error
  ? '数据已过期'
  : props.health?.status === 'healthy' ? '健康' : props.health?.status === 'degraded' ? '降级' : '等待首次同步')
const examinedCount = computed(() => (props.health?.startupReconciliation.examinedMissions || 0) + (props.health?.startupReconciliation.examinedRuns || 0))
const repairedCount = computed(() => (props.health?.startupReconciliation.repairedMissions || 0) + (props.health?.startupReconciliation.repairedRuns || 0))
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN')
</script>

<style scoped>
.identity-health { display: flex; align-items: center; gap: 18px; min-height: 50px; padding: 8px 14px; border-bottom: 1px solid var(--border-light); background: var(--bg-card); color: var(--text-primary); }
.identity-health.degraded, .identity-health.unknown { box-shadow: inset 3px 0 var(--warning); }
.identity-health.healthy { box-shadow: inset 3px 0 var(--success); }
.health-title { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.health-title > .el-icon { color: var(--success); }
.degraded .health-title > .el-icon, .unknown .health-title > .el-icon { color: var(--warning); }
.health-title div { display: grid; gap: 2px; }
.health-title strong { font-size: 12px; }
.health-title span, .health-meta, .health-metrics small { color: var(--text-secondary); font-size: 9px; }
.health-metrics { display: flex; align-items: center; gap: 5px; flex: 1 1 auto; min-width: 0; overflow-x: auto; }
.health-metrics > span { display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 4px; min-width: max-content; padding: 4px 7px; border-radius: 5px; background: var(--bg-input); }
.health-metrics b { font-size: 11px; }
.health-meta { display: grid; justify-items: end; gap: 2px; flex: 0 1 auto; text-align: right; }
.health-meta .stale { color: var(--warning); }
@media (max-width: 900px) { .identity-health { align-items: flex-start; flex-wrap: wrap; } .health-metrics { order: 3; flex-basis: 100%; } .health-meta { margin-left: auto; } }
@media (max-width: 560px) { .identity-health { gap: 10px; } .health-meta { flex-basis: 100%; justify-items: start; text-align: left; } }
</style>
