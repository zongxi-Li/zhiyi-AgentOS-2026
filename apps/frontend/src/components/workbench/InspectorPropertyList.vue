<template>
  <dl class="property-list">
    <div v-for="row in rows" :key="row.label" class="property-row">
      <dt>{{ inspectorLabel(row.label) }}</dt>
      <dd
        :title="codeTitle(row)"
        :class="{ 'is-code': row.code, 'is-empty': row.value == null || row.value === '', 'is-copied': copiedLabel === row.label }"
        @click="copyCode(row)"
      >{{ row.value == null || row.value === '' ? (row.emptyLabel || '暂未提供') : row.code ? row.value : inspectorValue(row.value) }}</dd>
    </div>
  </dl>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { inspectorLabel, inspectorValue } from '@/workbench/runtime/inspectorPresentation'
export interface InspectorProperty {
  label: string
  value?: string | number | null
  code?: boolean
  emptyLabel?: string
}

defineProps<{
  rows: InspectorProperty[]
}>()

/* code 值点击即复制（写入剪贴板 + 短暂 ✓ 反馈）；不可用时回退为整段选中 */
const copiedLabel = ref('')
let copiedTimer = 0
const codeTitle = (row: InspectorProperty) => {
  if (!row.code || row.value == null || row.value === '') return undefined
  return `${row.value} · 点击复制`
}
const copyCode = async (row: InspectorProperty) => {
  if (!row.code || row.value == null || row.value === '') return
  try {
    if (!navigator.clipboard?.writeText) return
    await navigator.clipboard.writeText(String(row.value))
    copiedLabel.value = row.label
    clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => { copiedLabel.value = '' }, 1200)
  } catch { /* 剪贴板不可用时保持原生选中复制 */ }
}
</script>

<style scoped>
.property-list { margin: 0; }
.property-list { container-type: inline-size; }
.property-row { display: grid; grid-template-columns: minmax(64px, 88px) minmax(0, 1fr); gap: 10px; align-items: start; min-height: 30px; padding: 6px 0; font-size: 12px; line-height: 1.65; }
.property-row dt { min-width: 0; padding-top: 1px; color: var(--wb-text-muted); font-size: 11px; overflow-wrap: anywhere; }
.property-row dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--wb-text); text-align: left; }
/* code 值：内凹复制井，点击写剪贴板并短暂变绿打勾 */
.property-row dd.is-code { width: fit-content; max-width: 100%; padding: 2px 9px; border-radius: 8px; user-select: text; cursor: copy; color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 11px/1.7 var(--font-mono, monospace); box-shadow: inset 1px 1px 3px color-mix(in srgb, #000 28%, transparent), inset -1px -1px 3px color-mix(in srgb, #fff 3.5%, transparent); transition: color 160ms ease, box-shadow 160ms ease; }
.property-row dd.is-code:hover { color: var(--wb-text); }
.property-row dd.is-code.is-copied { cursor: default; color: var(--wb-success); box-shadow: inset 1px 1px 3px color-mix(in srgb, #000 28%, transparent), inset -1px -1px 3px color-mix(in srgb, #fff 3.5%, transparent), 0 0 0 1px color-mix(in srgb, var(--wb-success) 32%, transparent); }
.property-row dd.is-code.is-copied::after { content: ' ✓'; }
.property-row dd.is-empty { color: var(--wb-text-muted); }
@container (max-width: 260px) { .property-row { grid-template-columns: 1fr; gap: 2px; padding: 8px 0; } }
</style>
