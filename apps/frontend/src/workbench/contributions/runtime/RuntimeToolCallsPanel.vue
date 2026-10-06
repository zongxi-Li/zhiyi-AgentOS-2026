<template>
  <section class="runtime-panel" aria-label="Tool Calls">
    <header class="runtime-panel__intro">
      <strong>Tool Calls</strong>
      <span class="runtime-panel__intro-side">
        <span>{{ items.length }} calls · source trace</span>
        <button class="runtime-panel__close" type="button" title="关闭运行面板" aria-label="关闭运行面板" @click="emit('close')">
          <el-icon aria-hidden="true"><Close /></el-icon>
        </button>
      </span>
    </header>
    <BrandEmpty v-if="!items.length" class="runtime-panel__empty" text="Empty / 未观测 Tool Call。" />
    <div v-else class="runtime-panel__list">
      <button v-for="item in items" :key="item.eventId" type="button" class="runtime-panel__row" @click="selectItem(item.stepId)">
        <span class="runtime-panel__main">
          <strong>{{ item.tool || item.name || 'Tool 未观测' }}</strong>
          <small>{{ item.name || item.stepId || '节点未观测' }} · {{ item.status || '状态未观测' }}</small>
        </span>
        <span class="runtime-panel__meta">
          <span>{{ item.startedAt ? formatDate(item.startedAt) : 'startedAt 未观测' }}</span>
          <span>{{ item.durationMs == null ? 'duration 未观测' : `${item.durationMs} ms` }}</span>
          <span v-if="item.latencyMs != null">latency {{ item.latencyMs }} ms</span>
        </span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BrandEmpty from '@/components/common/BrandEmpty.vue'
import type { RuntimeObservation, RuntimeSelection } from '@/workbench/runtime/observation'

const props = defineProps<{ runtimeObservation: RuntimeObservation | null }>()
const emit = defineEmits<{ select: [selection: RuntimeSelection]; close: [] }>()
const items = computed(() => props.runtimeObservation?.toolCalls || [])
const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN')
const selectItem = (stepId: string | null) => emit('select', { stepId })
</script>

<style scoped>
.runtime-panel { display: flex; flex-direction: column; min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.runtime-panel__intro { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 33px; box-sizing: border-box; padding: 8px 14px; }
.runtime-panel__intro strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; text-transform: uppercase; }
.runtime-panel__intro span, .runtime-panel__row small { color: var(--wb-text-muted); font-size: 10px; }
.runtime-panel__intro-side { display: inline-flex; align-items: center; gap: 8px; align-self: center; }
.runtime-panel__close { display: inline-grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--wb-text-muted); font-size: 13px; line-height: 1; cursor: pointer; transition: background-color 140ms var(--ease-out, ease), color 140ms var(--ease-out, ease); }
.runtime-panel__close:hover, .runtime-panel__close:focus-visible { background: var(--wb-hover); color: var(--wb-accent); outline: none; }
.runtime-panel__list { display: grid; align-content: start; }
.runtime-panel__row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(190px, auto); align-items: center; gap: 12px; width: 100%; padding: 8px 14px; border: 0; border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 68%, transparent); color: inherit; background: transparent; text-align: left; cursor: pointer; }
.runtime-panel__row:hover { background: var(--wb-hover); }
.runtime-panel__row:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
.runtime-panel__main { display: grid; gap: 4px; min-width: 0; }
.runtime-panel__main strong { overflow: hidden; color: var(--wb-text); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__meta { display: flex; gap: 10px; color: var(--wb-text-muted); font-size: 10px; white-space: nowrap; }
.runtime-panel__empty { flex: 1; margin: 0; }
@media (max-width: 720px) { .runtime-panel__row { grid-template-columns: 1fr; gap: 5px; } .runtime-panel__meta { flex-wrap: wrap; white-space: normal; } }
</style>
