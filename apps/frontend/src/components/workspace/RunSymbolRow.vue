<template>
  <div
    class="run-symbol"
    :class="rowClasses"
    :data-symbol-id="symbol.id"
    :data-symbol-type="symbol.type"
  >
    <EditorObjectRow
      :depth="horizontal ? 0 : depth"
      :selected="selectedSymbolId === symbol.id"
    >
      <template #gutter>
        <span class="run-symbol__status" :class="`is-${symbol.status}`" aria-hidden="true">{{ statusMark }}</span>
      </template>
      <button
        type="button"
        class="run-symbol__main"
        :class="{
          'run-progress-group__head': symbol.type === 'planner' || symbol.type === 'task'
        }"
        :aria-current="selectedSymbolId === symbol.id ? 'true' : undefined"
        @click="handleMainClick"
        @dblclick="emit('open', symbol)"
      >
        <span class="run-symbol__title" :title="symbol.title">{{ symbol.title }}</span>
        <span v-if="symbol.subtitle" class="run-symbol__subtitle">{{ symbol.subtitle }}</span>
      </button>
      <template #meta>
        <button
          v-if="symbol.type === 'artifact'"
          type="button"
          class="run-progress-artifact__open run-symbol__action"
          @click.stop="emit('open', symbol)"
        >打开</button>
      </template>
    </EditorObjectRow>

    <p v-if="symbol.detail && horizontal" class="run-symbol__detail run-progress-group__note">{{ symbol.detail }}</p>

    <div v-if="isOpen && !horizontal" class="run-symbol__body">
      <div v-if="symbol.metrics && Object.keys(symbol.metrics).length" class="run-symbol__metrics">
        <span v-for="(value, key) in symbol.metrics" :key="key">{{ key }} {{ formatMetric(String(key), value) }}</span>
      </div>
      <p v-if="symbol.detail" class="run-symbol__detail run-progress-group__note">{{ symbol.detail }}</p>
      <div v-if="hasChildren" class="run-symbol__children">
        <RunSymbolRow
          v-for="child in symbol.children"
          :key="child.id"
          :symbol="child"
          :selected-symbol-id="selectedSymbolId"
          :is-expanded="isExpanded"
          :is-current="isCurrentSymbol(child)"
          :depth="depth + 1"
          :horizontal="horizontal"
          @toggle="emit('toggle', $event)"
          @select="emit('select', $event)"
          @open="emit('open', $event)"
        />
      </div>
    </div>
    <pre
      v-if="symbol.content"
      v-show="horizontal || isOpen"
      class="run-symbol__content"
      :data-testid="symbol.title === 'Structured Output' ? 'planner-live-output' : undefined"
    >{{ symbol.content }}</pre>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'
import EditorObjectRow from './EditorObjectRow.vue'

const props = withDefaults(defineProps<{
  symbol: RunDocumentSymbol
  selectedSymbolId?: string | null
  isExpanded: (symbol: RunDocumentSymbol) => boolean
  isCurrent?: boolean
  depth?: number
  horizontal?: boolean
}>(), {
  selectedSymbolId: null,
  isCurrent: false,
  depth: 0,
  horizontal: false
})

const emit = defineEmits<{
  toggle: [symbol: RunDocumentSymbol]
  select: [symbol: RunDocumentSymbol]
  open: [symbol: RunDocumentSymbol]
}>()

const hasChildren = computed(() => props.symbol.children.length > 0 || (!props.horizontal && Boolean(props.symbol.content)))
const isOpen = computed(() => props.isExpanded(props.symbol))
const currentTypes = new Set<RunDocumentSymbol['type']>(['planner', 'stage', 'task', 'model', 'tool'])
const isCurrent = computed(() => props.isCurrent || (props.symbol.status === 'running' && currentTypes.has(props.symbol.type)))
const statusMark = computed(() => ({
  running: '●',
  completed: '✓',
  warning: '!',
  failed: '×',
  pending: '○'
}[props.symbol.status]))
const rowClasses = computed(() => ({
  'is-open': isOpen.value,
  'is-current': isCurrent.value,
  'is-selected': props.selectedSymbolId === props.symbol.id,
  'run-progress-group': ['planner', 'execution', 'task'].includes(props.symbol.type),
  'run-progress-tool': props.symbol.type === 'tool',
  'run-progress-artifact': props.symbol.type === 'artifact'
}))

const isCurrentSymbol = (symbol: RunDocumentSymbol) => symbol.status === 'running' && currentTypes.has(symbol.type)
const formatMetric = (key: string, value: string | number) => {
  if (['TTFT', 'Idle'].includes(key) && typeof value === 'number') return `${value} ms`
  return String(value)
}
const handleMainClick = () => {
  emit('select', props.symbol)
  if (hasChildren.value) emit('toggle', props.symbol)
}
</script>

<style scoped>
.run-symbol { min-width: 0; color: var(--wb-text); }
.run-symbol__status { width: 15px; flex: 0 0 15px; color: var(--wb-text-muted); font-size: 11px; text-align: center; }
.run-symbol__status.is-running { color: var(--wb-accent); }
.run-symbol__status.is-completed { color: var(--wb-success); }
.run-symbol__status.is-warning { color: var(--wb-warning); }
.run-symbol__status.is-failed { color: var(--wb-danger); }
.run-symbol__main { display: grid; grid-template-columns: minmax(160px, .9fr) minmax(0, 1.8fr); align-items: baseline; gap: 12px; min-width: 0; width: auto; min-height: 24px; padding: 2px 6px; border: 0; color: var(--wb-text); background: transparent; cursor: pointer; text-align: left; }
.run-symbol__main:hover { color: var(--wb-text); background: var(--wb-hover); }
.run-symbol__main:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: -1px; }
.run-symbol__title { min-width: 0; overflow: hidden; font-size: 12px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.run-symbol__title:only-child { grid-column: 1 / -1; }
.run-symbol[data-symbol-type='planner'] .run-symbol__title,
.run-symbol[data-symbol-type='execution'] .run-symbol__title,
.run-symbol[data-symbol-type='task'] .run-symbol__title { font-weight: 650; }
.run-symbol__subtitle { min-width: 0; overflow: hidden; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.run-symbol__action { flex: 0 0 auto; margin: 0 5px 0 6px; padding: 2px 6px; border: 1px solid color-mix(in srgb, var(--wb-accent) 34%, var(--wb-border)); border-radius: var(--wb-radius-sm); color: var(--wb-accent); background: transparent; cursor: pointer; font-size: 10px; opacity: 0; pointer-events: none; white-space: nowrap; }
.run-symbol:hover .run-symbol__action, .run-symbol__action:focus-visible { opacity: 1; pointer-events: auto; }
.run-symbol__action:hover { border-color: var(--wb-accent); background: var(--wb-accent-soft); }
.run-symbol__body { min-width: 0; padding: 1px 0 5px 42px; border-left: 1px solid var(--wb-border-soft); margin-left: 7px; }
.run-symbol__children { min-width: 0; }
.run-symbol__children > .run-symbol { position: relative; }
.run-symbol__metrics { display: flex; flex-wrap: wrap; gap: 3px 12px; margin: 2px 8px 5px 0; color: var(--wb-text-muted); font: 10px/1.45 var(--font-mono, monospace); }
.run-symbol__metrics span { overflow-wrap: anywhere; }
.run-symbol__detail { margin: 3px 8px 6px 0; color: var(--wb-text-secondary); font-size: 11px; line-height: 1.5; }
.run-symbol__content { max-height: 220px; margin: 4px 8px 7px 0; padding: 8px; overflow: auto; border: 1px solid var(--wb-border-soft); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 10px/1.5 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.run-symbol[data-symbol-type='runtime'] .run-symbol__title { color: var(--wb-text-secondary); }
.run-symbol[data-symbol-type='agent'] .run-symbol__title,
.run-symbol[data-symbol-type='tool'] .run-symbol__title,
.run-symbol[data-symbol-type='artifact'] .run-symbol__title { color: var(--wb-text-secondary); }

@media (max-width: 720px) {
  .run-symbol__body { padding-left: 32px; }
  .run-symbol__action { display: none; }
  .run-symbol__main { grid-template-columns: minmax(100px, .9fr) minmax(0, 1.2fr); gap: 6px; }
}
</style>
