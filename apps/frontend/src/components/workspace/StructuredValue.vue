<template>
  <div v-if="isPrimitive && markdown" class="structured-value__markdown" v-html="renderedMarkdown" />
  <span v-else-if="isPrimitive" class="structured-value__text" :class="{ 'is-long': isLongText }">{{ primitiveText }}</span>
  <div v-else-if="Array.isArray(value)" class="structured-value__list">
    <article v-for="(item, index) in value" :key="`${depth}-${index}`" class="structured-value__item">
      <span class="structured-value__index">{{ String(index + 1).padStart(2, '0') }}</span>
      <div class="structured-value__item-value">
        <StructuredValue :value="item" :depth="depth + 1" />
      </div>
    </article>
  </div>
  <dl v-else class="structured-value__object">
    <div v-for="[key, item] in objectEntries" :key="key" class="structured-value__field">
      <dt>{{ labelForKey(key) }}</dt>
      <dd><StructuredValue :value="item" :depth="depth + 1" :markdown="isRichTextKey(key)" /></dd>
    </div>
  </dl>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

defineOptions({ name: 'StructuredValue' })

const props = withDefaults(defineProps<{
  value: unknown
  depth?: number
  markdown?: boolean
}>(), {
  depth: 0,
  markdown: false
})

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
)
const isPrimitive = computed(() => !Array.isArray(props.value) && !isRecord(props.value))
const primitiveText = computed(() => {
  if (props.value == null) return '—'
  if (typeof props.value === 'boolean') return props.value ? 'true' : 'false'
  if (typeof props.value === 'string') return props.value
  return String(props.value)
})
const isLongText = computed(() => typeof props.value === 'string' && (props.value.length > 180 || props.value.includes('\n')))
const renderedMarkdown = computed(() => renderMarkdown(primitiveText.value))
const objectEntries = computed(() => isRecord(props.value) ? Object.entries(props.value) : [])
const labels: Record<string, string> = {
  overview: '\u6982\u8981',
  objective: '\u76ee\u6807',
  summary: '\u6458\u8981',
  phases: '\u9636\u6bb5',
  deliverables: '\u4ea4\u4ed8\u7269',
  dependencies: '\u4f9d\u8d56',
  milestones: '\u91cc\u7a0b\u7891',
  acceptance_criteria: '\u9a8c\u6536\u6807\u51c6',
  constraints: '\u7ea6\u675f',
  assumptions: '\u5047\u8bbe',
  risks: '\u98ce\u9669',
  content: '\u5185\u5bb9',
  name: '\u540d\u79f0',
  status: '\u72b6\u6001',
  source: '\u6765\u6e90'
}
const labelForKey = (key: string) => labels[key] || key.split('_').join(' ')
const isRichTextKey = (key: string) => ['content', 'overview', 'description', 'summary', 'final_answer', 'report', 'report_markdown'].includes(key)
</script>

<style scoped>
.structured-value__text { display: block; min-width: 0; color: var(--wb-text-secondary); line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.structured-value__text.is-long { padding: 7px 9px; border-left: 2px solid color-mix(in srgb, var(--wb-accent) 42%, var(--wb-border)); background: color-mix(in srgb, var(--wb-surface-inset) 78%, transparent); }
.structured-value__markdown { min-width: 0; color: var(--wb-text-secondary); line-height: 1.6; overflow-wrap: anywhere; }
.structured-value__markdown :deep(h1), .structured-value__markdown :deep(h2), .structured-value__markdown :deep(h3) { margin: 0 0 7px; color: var(--wb-text); line-height: 1.35; }
.structured-value__markdown :deep(h1) { font-size: 16px; }
.structured-value__markdown :deep(h2) { font-size: 14px; }
.structured-value__markdown :deep(h3) { font-size: 13px; }
.structured-value__markdown :deep(p), .structured-value__markdown :deep(li) { margin: 0 0 5px; }
.structured-value__markdown :deep(ul), .structured-value__markdown :deep(ol) { margin: 0 0 5px; padding-left: 18px; }
.structured-value__markdown :deep(pre) { max-width: 100%; overflow: auto; padding: 6px 8px; background: var(--wb-surface-inset); font: 10px/1.5 var(--font-mono, monospace); }
.structured-value__list { display: grid; gap: 6px; min-width: 0; }
.structured-value__item { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 8px; min-width: 0; padding: 6px 0; border-bottom: 1px solid color-mix(in srgb, var(--wb-border-soft) 72%, transparent); }
.structured-value__item:last-child { border-bottom: 0; }
.structured-value__index { color: var(--wb-accent); font: 10px/1.6 var(--font-mono, monospace); text-align: right; }
.structured-value__item-value { min-width: 0; }
.structured-value__object { display: grid; gap: 7px; min-width: 0; margin: 0; }
.structured-value__field { display: grid; grid-template-columns: minmax(90px, 28%) minmax(0, 1fr); gap: 10px; min-width: 0; }
.structured-value__field dt { color: var(--wb-text-muted); font-size: 11px; }
.structured-value__field dd { min-width: 0; margin: 0; }
</style>
