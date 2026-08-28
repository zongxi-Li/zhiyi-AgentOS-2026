<template>
  <button
    class="resource-strip"
    type="button"
    aria-haspopup="dialog"
    aria-controls="acg-resource-drawer"
    aria-label="打开资源详情"
    @click="$emit('open')"
  >
    <span class="resource-model"><i aria-hidden="true"></i>{{ modelLabel }}<em v-if="declared" class="resource-declared">预计</em></span>
    <span>调用 <b>{{ usage?.usage.callCount ?? '—' }}</b></span>
    <span>输入 <b>{{ observed(usage?.usage.inputTokens) }}</b></span>
    <span>输出 <b>{{ observed(usage?.usage.outputTokens) }}</b></span>
    <span>缓存命中 <b>{{ percent(usage?.usage.cacheHitRatio) }}</b></span>
    <span>上下文峰值 <b>{{ percent(usage?.contextPressure.peak, '上限未声明') }}</b></span>
    <span>报告装配 <b>{{ assembly }}</b></span>
    <span class="resource-more">资源详情 <span aria-hidden="true">›</span></span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RunResourceUsage } from '@/services/api/workflow'

const props = defineProps<{ usage?: RunResourceUsage | null }>()
defineEmits<{ open: [] }>()
const declared = computed(() => props.usage?.capabilitySource === 'declared')
const modelLabel = computed(() => {
  const capability = props.usage?.capability
  if (!capability) return 'API 未声明'
  const policy = {
    api_controlled: 'API 控制',
    provider_required: '供应商必需',
    explicit: '显式声明',
    catalog_default: '目录预算'
  }[props.usage?.outputPolicy || ''] || '未知'
  return `${capability.model || capability.provider} · ${policy}`
})
const assembly = computed(() => {
  const value = props.usage?.composition
  if (!value) return '—'
  return `${value.chapterCount} 章 · ${value.assemblyComplete ? '已完成' : '进行中'}`
})
const compact = (value?: number | null) => {
  if (value === null || value === undefined) return '—'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(value)
}
const observed = (value?: number | null) => props.usage?.usage.callCount ? compact(value) : '未观测'
const percent = (value?: number | null, empty = '—') => value === null || value === undefined
  ? empty
  : `${Math.round(value * 100)}%`
</script>

<style scoped>
.resource-declared { font-style: normal; margin-left: 4px; padding: 1px 4px; border-radius: 4px; border: 1px solid color-mix(in srgb, var(--primary-color) 35%, transparent); color: var(--primary-color); font-size: 9px; line-height: 1.4; }

.resource-strip {
  box-sizing: border-box; width: 100%; min-width: 0; display: flex; align-items: center; gap: 7px 16px;
  padding: 10px 16px; border: 0; border-top: 1px solid var(--border-light); background: transparent;
  color: var(--text-secondary); font: inherit; font-size: 10px; text-align: left; cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}
.resource-strip:hover { background: color-mix(in srgb, var(--primary-color) 4%, transparent); color: var(--text-primary); }
.resource-strip:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
.resource-strip span { white-space: nowrap; }
.resource-strip b { color: var(--text-primary); font-weight: 700; }
.resource-model { display: inline-flex; align-items: center; gap: 6px; color: var(--text-primary); font-weight: 700; }
.resource-model i { width: 7px; height: 7px; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 3px var(--success-fade); }
.resource-more { margin-left: auto; color: var(--primary-color); font-weight: 700; }
@media (max-width: 760px) { .resource-strip { overflow-x: auto; scrollbar-width: none; } .resource-more { margin-left: 0; } }
@media (prefers-reduced-motion: reduce) { .resource-strip { transition: none; } }
</style>
