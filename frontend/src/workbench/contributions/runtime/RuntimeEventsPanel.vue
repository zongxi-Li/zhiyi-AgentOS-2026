<template>
  <section class="runtime-panel" aria-label="Events">
    <header class="runtime-panel__intro">
      <strong>Events</strong>
      <label>
        <span class="sr-only">筛选事件类型</span>
        <select v-model="eventType">
          <option value="all">全部类型</option>
          <option v-for="type in eventTypes" :key="type" :value="type">{{ type }}</option>
        </select>
      </label>
    </header>
    <p v-if="!filteredItems.length" class="runtime-panel__empty">Empty / 未观测 Runtime Event。</p>
    <div v-else class="runtime-panel__list">
      <button v-for="item in filteredItems" :key="item.eventId" type="button" class="runtime-panel__row" @click="selectItem(item.stepId)">
        <time>{{ formatDate(item.timestamp) }}</time>
        <span class="runtime-panel__main">
          <strong>{{ item.eventType }}</strong>
          <small>{{ item.summary }}</small>
        </span>
        <span class="runtime-panel__meta">{{ item.target || 'target 未观测' }}</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RuntimeObservation, RuntimeSelection } from '@/workbench/runtime/observation'

const props = defineProps<{ runtimeObservation: RuntimeObservation | null }>()
const emit = defineEmits<{ select: [selection: RuntimeSelection] }>()
const eventType = ref('all')
const items = computed(() => props.runtimeObservation?.events || [])
const eventTypes = computed(() => [...new Set(items.value.map(item => item.eventType))].sort())
const filteredItems = computed(() => eventType.value === 'all' ? items.value : items.value.filter(item => item.eventType === eventType.value))
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '时间未观测'
const selectItem = (stepId: string | null) => emit('select', { stepId })
</script>

<style scoped>
.runtime-panel { min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.runtime-panel__intro { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 33px; box-sizing: border-box; padding: 7px 14px; border-bottom: 1px solid var(--wb-border); }
.runtime-panel__intro strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; text-transform: uppercase; }
.runtime-panel select { min-height: 25px; padding: 0 7px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: inherit; font-size: 10px; }
.runtime-panel select:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 1px; }
.runtime-panel__list { display: grid; align-content: start; }
.runtime-panel__row { display: grid; grid-template-columns: 116px minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; padding: 8px 14px; border: 0; border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 68%, transparent); color: inherit; background: transparent; text-align: left; cursor: pointer; }
.runtime-panel__row:hover { background: var(--wb-hover); }
.runtime-panel__row:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
.runtime-panel__row time, .runtime-panel__row small, .runtime-panel__meta { color: var(--wb-text-muted); font-size: 10px; }
.runtime-panel__main { display: grid; gap: 4px; min-width: 0; }
.runtime-panel__main strong { overflow: hidden; color: var(--wb-text); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__meta { white-space: nowrap; }
.runtime-panel__empty { margin: 0; padding: 24px 14px; color: var(--wb-text-muted); font-size: 11px; text-align: center; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
</style>
