<template>
  <dl class="property-list">
    <div v-for="row in rows" :key="row.label" class="property-row">
      <dt>{{ row.label }}</dt>
      <dd
        :title="row.value == null || row.value === '' ? undefined : String(row.value)"
        :class="{ 'is-code': row.code, 'is-empty': row.value == null || row.value === '' }"
      >{{ row.value == null || row.value === '' ? '—' : row.value }}</dd>
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
.property-row { display: grid; grid-template-columns: 132px minmax(0, 1fr); gap: 12px; min-height: 34px; padding: 7px 0; font-size: 12px; }
.property-row + .property-row { border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.property-row dt { overflow: hidden; color: var(--wb-text-muted); text-overflow: ellipsis; white-space: nowrap; }
.property-row dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--wb-text); text-align: left; }
.property-row dd.is-code { color: var(--wb-text-secondary); font: 10px/1.45 var(--font-mono, monospace); }
.property-row dd.is-empty { color: var(--wb-text-muted); }
</style>
