<template>
  <article
    class="runtime-event-row"
    :class="[`is-${item.kind}`, `is-${item.status}`]"
    role="button"
    tabindex="0"
    :aria-label="`${item.title}：${item.summary}`"
    @click="emit('select')"
    @keydown.enter.prevent="emit('select')"
    @keydown.space.prevent="emit('select')"
  >
    <div class="runtime-event-row__rail" aria-hidden="true">
      <span class="runtime-event-row__icon"><component :is="kindIcon" /></span>
      <span class="runtime-event-row__line"></span>
    </div>

    <div class="runtime-event-row__content">
      <div class="runtime-event-row__headline">
        <div class="runtime-event-row__copy">
          <strong>{{ item.title }}</strong>
          <span>{{ item.summary }}</span>
        </div>
        <div class="runtime-event-row__meta">
          <span class="runtime-event-row__status">{{ statusLabel }}</span>
          <span v-if="formattedDuration">{{ formattedDuration }}</span>
          <span v-if="item.timestamp">{{ formattedTime }}</span>
          <button
            v-if="item.expandable"
            class="runtime-event-row__toggle"
            type="button"
            :aria-expanded="expanded"
            :aria-label="expanded ? '收起事件详情' : '展开事件详情'"
            @click.stop="expanded = !expanded"
          >
            <el-icon><ArrowDown v-if="expanded" /><ArrowRight v-else /></el-icon>
          </button>
        </div>
      </div>

      <div v-if="expanded" class="runtime-event-row__details" @click.stop>
        <div v-for="detail in item.details" :key="`${detail.label}:${detail.value}`" class="runtime-event-row__detail">
          <span>{{ detail.label }}</span>
          <code v-if="detail.code">{{ detail.value }}</code>
          <p v-else>{{ detail.value }}</p>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowDown,
  ArrowRight,
  CircleCheckFilled,
  Connection,
  Cpu,
  Document,
  Operation,
  QuestionFilled,
  WarningFilled
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import type {
  RuntimePresentationKind,
  RuntimePresentationStatus,
  RuntimeSemanticPresentation
} from '@/workbench/runtime/runtimePresentation'

const props = defineProps<{ item: RuntimeSemanticPresentation }>()
const emit = defineEmits<{ select: [] }>()
const expanded = ref(false)

const kindIcon = computed<Component>(() => {
  const icons: Record<RuntimePresentationKind, Component> = {
    model: Cpu,
    tool: Connection,
    command: Operation,
    artifact: Document,
    error: WarningFilled,
    completion: CircleCheckFilled,
    generic: QuestionFilled
  }
  return icons[props.item.kind]
})

const statusLabel = computed(() => {
  const labels: Record<RuntimePresentationStatus, string> = {
    pending: '等待',
    running: '进行中',
    success: '完成',
    warning: '注意',
    failed: '失败',
    cancelled: '已取消',
    unknown: '未观测'
  }
  return labels[props.item.status]
})

const formattedTime = computed(() => {
  if (!props.item.timestamp) return ''
  const date = new Date(props.item.timestamp)
  return Number.isNaN(date.getTime()) ? '时间未观测' : date.toLocaleTimeString('zh-CN', { hour12: false })
})

const formattedDuration = computed(() => {
  const value = props.item.durationMs
  if (value == null) return ''
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} s`
})

</script>

<style scoped>
.runtime-event-row {
  position: relative;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
  padding: 7px 12px 7px 14px;
  border: 0;
  border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 42%, transparent);
  color: var(--wb-text-secondary);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms var(--ease-out), color 140ms var(--ease-out);
}

.runtime-event-row:hover,
.runtime-event-row:focus-visible { background: color-mix(in srgb, var(--wb-hover) 72%, transparent); outline: none; }
.runtime-event-row:focus-visible { box-shadow: inset 2px 0 0 var(--wb-accent); }
.runtime-event-row__rail { position: relative; display: flex; justify-content: center; min-height: 22px; }
.runtime-event-row__line { position: absolute; top: 20px; bottom: -7px; width: 1px; background: color-mix(in srgb, var(--wb-border) 72%, transparent); }
.runtime-event-row:last-child .runtime-event-row__line { display: none; }
.runtime-event-row__icon { z-index: 1; display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 5px; color: var(--wb-text-muted); background: var(--wb-surface-inset); font-size: 11px; }
.is-model .runtime-event-row__icon { color: var(--wb-accent); }
.is-tool .runtime-event-row__icon, .is-command .runtime-event-row__icon { color: var(--wb-info, var(--wb-accent)); }
.is-artifact .runtime-event-row__icon { color: var(--wb-artifact, var(--wb-accent)); }
.is-error .runtime-event-row__icon, .is-failed .runtime-event-row__icon { color: var(--wb-danger); }
.is-completion .runtime-event-row__icon, .is-success .runtime-event-row__icon { color: var(--wb-success); }
.is-running .runtime-event-row__icon { color: var(--wb-accent); }
.is-running .runtime-event-row__icon :deep(svg) { animation: runtime-event-pulse 1.6s ease-in-out infinite; }
.runtime-event-row__content { min-width: 0; }
.runtime-event-row__headline { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; min-width: 0; }
.runtime-event-row__copy { display: grid; gap: 2px; min-width: 0; }
.runtime-event-row__copy strong { overflow: hidden; color: var(--wb-text); font-size: 11px; font-weight: 650; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.runtime-event-row__copy > span { overflow: hidden; color: var(--wb-text-muted); font-size: 10px; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; text-wrap: pretty; }
.runtime-event-row__meta { display: flex; align-items: center; justify-content: flex-end; gap: 7px; flex: 0 0 auto; color: var(--wb-text-muted); font: 9px var(--font-mono, monospace); white-space: nowrap; }
.runtime-event-row__status { color: inherit; }
.is-running .runtime-event-row__status { color: var(--wb-accent); }
.is-success .runtime-event-row__status { color: var(--wb-success); }
.is-failed .runtime-event-row__status { color: var(--wb-danger); }
.is-warning .runtime-event-row__status { color: var(--wb-warning); }
.runtime-event-row__toggle { display: inline-grid; place-items: center; width: 20px; height: 20px; padding: 0; border: 0; border-radius: 4px; color: var(--wb-text-muted); background: transparent; cursor: pointer; }
.runtime-event-row__toggle:hover, .runtime-event-row__toggle:focus-visible { color: var(--wb-text); background: var(--wb-hover); outline: none; }
.runtime-event-row__details { display: grid; gap: 4px; margin-top: 7px; padding: 6px 8px; border-left: 1px solid color-mix(in srgb, var(--wb-accent) 42%, var(--wb-border)); color: var(--wb-text-muted); background: color-mix(in srgb, var(--wb-surface-inset) 62%, transparent); }
.runtime-event-row__detail { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 8px; align-items: baseline; min-width: 0; font-size: 9px; line-height: 1.35; }
.runtime-event-row__detail > span { color: var(--wb-text-muted); font: 9px var(--font-mono, monospace); }
.runtime-event-row__detail code, .runtime-event-row__detail p { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--wb-text-secondary); font: inherit; }
.runtime-event-row__detail code { color: var(--wb-text); }

@keyframes runtime-event-pulse { 50% { opacity: .46; } }
@media (prefers-reduced-motion: reduce) { .runtime-event-row, .runtime-event-row__icon :deep(svg) { transition: none; animation: none; } }
@media (max-width: 720px) { .runtime-event-row__headline { display: grid; gap: 4px; } .runtime-event-row__meta { justify-content: flex-start; } }
</style>
