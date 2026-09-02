<template>
  <section class="model-output-panel" aria-label="Model Output">
    <header class="model-output-panel__intro"><strong>MODEL OUTPUT</strong><span v-if="latest">{{ latest }}</span></header>
    <div v-if="!items.length" class="model-output-panel__empty">启动运行后，这里会显示模型当前正在处理的阶段。</div>
    <div v-else class="model-output-panel__list" aria-live="polite">
      <div v-for="item in items" :key="item.eventId" class="model-output-panel__row">
        <span class="model-output-panel__dot" :class="'is-' + status(item)" aria-hidden="true"></span>
        <div><p>{{ message(item) }}</p><small>{{ formatDate(item.timestamp) }}<span v-if="retryCount(item) > 0"> · 第 {{ retryCount(item) + 1 }} 次尝试</span></small></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeObservation, RuntimeTraceObservation } from '@/workbench/runtime/observation'
const props = defineProps<{ runtimeObservation: RuntimeObservation | null }>()
const items = computed(() => (props.runtimeObservation?.traces || []).filter(item => item.payload.planningProgress))
const latest = computed(() => items.value.length ? message(items.value[items.value.length - 1]) : '')
const formatDate = (value: string | null) => value ? new Date(value).toLocaleTimeString('zh-CN') : ''
const stageName = (item: RuntimeTraceObservation) => String(item.payload.stage || 'planning')
const status = (item: RuntimeTraceObservation) => String(item.payload.status || 'updated')
const retryCount = (item: RuntimeTraceObservation) => Number(item.payload.retryCount || 0)
const message = (item: RuntimeTraceObservation) => {
  const stage = stageName(item); const state = status(item)
  if (state === 'retrying') return '连接中断，正在重试 ' + stage
  if (state === 'completed') return stage + ' 已完成，继续整理结果'
  if (state === 'started') {
    if (stage === 'intent_profile') return '正在理解任务目标和约束'
    if (stage === 'outline') return '正在规划任务结构'
    if (stage === 'detail') return '正在补充任务细节和验收条件'
    if (stage === 'relations') return '正在检查任务依赖关系'
    return '正在分析任务'
  }
  return '正在整理规划结果'
}
</script>

<style scoped>
.model-output-panel { min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.model-output-panel__intro { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 8px 14px; border-bottom: 1px solid var(--wb-border); }
.model-output-panel__intro strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.model-output-panel__intro span, .model-output-panel__row small { color: var(--wb-text-muted); font-size: 10px; }
.model-output-panel__list { display: grid; align-content: start; }
.model-output-panel__row { display: grid; grid-template-columns: 8px minmax(0, 1fr); gap: 10px; padding: 9px 14px; border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 68%, transparent); }
.model-output-panel__dot { width: 7px; height: 7px; margin-top: 4px; border-radius: 50%; background: var(--wb-accent); }
.model-output-panel__dot.is-retrying { background: var(--wb-warning); }
.model-output-panel__dot.is-completed { background: var(--wb-success); }
.model-output-panel__row p { margin: 0 0 4px; color: var(--wb-text); font-size: 12px; }
.model-output-panel__empty { padding: 24px 14px; color: var(--wb-text-muted); font-size: 11px; }
</style>
