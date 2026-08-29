<template>
  <section class="runtime-panel" aria-label="Communication">
    <header class="runtime-panel__intro">
      <strong>Communication</strong>
      <span>只读投影 · provenance / trace</span>
    </header>
    <p v-if="!items.length" class="runtime-panel__empty">Empty / 未观测通信记录。</p>
    <div v-else class="runtime-panel__list">
      <button v-for="item in items" :key="item.id" type="button" class="runtime-panel__row" @click="selectItem(item)">
        <span class="runtime-panel__marker" aria-hidden="true">↔</span>
        <span class="runtime-panel__main">
          <strong>{{ item.summary }}</strong>
          <small>{{ item.source }} · {{ formatDate(item.timestamp) }} · {{ item.status || '未观测状态' }}</small>
        </span>
        <span class="runtime-panel__meta">{{ item.tokenCount == null ? 'Token 未观测' : `${item.tokenCount} Token` }}</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeCommunicationObservation, RuntimeObservation, RuntimeSelection } from '@/workbench/runtime/observation'

const props = defineProps<{ runtimeObservation: RuntimeObservation | null }>()
const emit = defineEmits<{ select: [selection: RuntimeSelection] }>()
const items = computed(() => props.runtimeObservation?.communication || [])

const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '时间未观测'
const selectItem = (item: RuntimeCommunicationObservation) => emit('select', { stepId: item.consumerStepId })
</script>

<style scoped>
.runtime-panel { min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.runtime-panel__intro { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 33px; box-sizing: border-box; padding: 8px 14px; border-bottom: 1px solid var(--wb-border); }
.runtime-panel__intro strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; text-transform: uppercase; }
.runtime-panel__intro span, .runtime-panel__row small { color: var(--wb-text-muted); font-size: 10px; }
.runtime-panel__list { display: grid; align-content: start; }
.runtime-panel__row { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; gap: 8px; width: 100%; padding: 8px 14px; border: 0; border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 68%, transparent); color: inherit; background: transparent; text-align: left; cursor: pointer; }
.runtime-panel__row:hover { background: var(--wb-hover); }
.runtime-panel__row:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
.runtime-panel__marker { color: var(--wb-accent); font-size: 14px; }
.runtime-panel__main { display: grid; gap: 4px; min-width: 0; }
.runtime-panel__main strong { overflow: hidden; color: var(--wb-text); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__meta { color: var(--wb-text-muted); font-size: 10px; white-space: nowrap; }
.runtime-panel__empty { margin: 0; padding: 24px 14px; color: var(--wb-text-muted); font-size: 11px; text-align: center; }
</style>
