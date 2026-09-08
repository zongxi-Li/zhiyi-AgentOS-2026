<template>
    <InspectorSection title="Result" :badge="selectedSymbol?.subtitle || 'selected'">
      <div class="task-result-inspector__title">{{ selectedSymbol?.title }}</div>
      <StructuredValue v-if="parsedValue" :value="parsedValue" />
      <InspectorPropertyList v-else :rows="rows" />
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceEntry } from '@/services/api/agentos'
import InspectorPropertyList, { type InspectorProperty } from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import StructuredValue from '@/components/workspace/StructuredValue.vue'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'

const props = defineProps<{
  entry: WorkspaceEntry
  selectedSymbol: RunDocumentSymbol | null
}>()

const parsedValue = computed<Record<string, unknown> | null>(() => {
  const source = props.selectedSymbol?.content
  if (!source) return null
  try {
    const value = JSON.parse(source) as unknown
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
  } catch {
    return null
  }
})
const displayValue = (value: unknown) => {
  if (value === true) return 'Hard'
  if (value === false) return 'Advisory'
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value) }
}
const rows = computed<InspectorProperty[]>(() => {
  const value = parsedValue.value
  if (!value) return [
    { label: 'Section', value: props.selectedSymbol?.detail || 'Result' },
    { label: 'Run ID', value: props.selectedSymbol?.runId, code: true },
    { label: 'semanticTaskKey', value: props.entry.semanticTaskKey, code: true }
  ]
  return Object.entries(value).map(([key, item]) => ({
    label: key === 'mandatory' || key === 'required' ? 'Type' : key === 'source' || key === 'sourceRef' ? 'Reference' : key,
    value: displayValue(item),
    code: key === 'source' || key === 'sourceRef' || key === 'provenance'
  }))
})
</script>

<style scoped>
.task-result-inspector__title { margin-bottom: 9px; color: var(--wb-text); font-size: 13px; line-height: 1.5; }
</style>
