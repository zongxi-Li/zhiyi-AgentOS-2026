<template>
  <dl class="property-list">
    <div v-for="row in rows" :key="row.label" class="property-row">
      <dt>{{ row.label }}</dt>
      <dd :class="{ 'is-code': row.code }">{{ row.value == null || row.value === '' ? '—' : row.value }}</dd>
    </div>
  </dl>
</template>

<script setup lang="ts">
export interface InspectorProperty {
  label: string
  value?: string | number | null
  code?: boolean
}

defineProps<{
  rows: InspectorProperty[]
}>()
</script>

<style scoped>
.property-list { margin: 0; }
.property-row { display: grid; grid-template-columns: minmax(92px, 42%) minmax(0, 1fr); gap: 10px; min-height: 30px; padding: 7px 0; border-bottom: 1px solid color-mix(in srgb, var(--border-light) 70%, transparent); font-size: 11px; }
.property-row dt { overflow: hidden; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; }
.property-row dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--text-secondary); text-align: right; }
.property-row dd.is-code { color: var(--text-primary); font: 10px var(--font-mono, monospace); }
</style>
