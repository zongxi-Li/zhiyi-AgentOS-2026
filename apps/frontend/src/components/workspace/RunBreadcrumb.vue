<template>
  <nav class="run-breadcrumb" aria-label="Run document breadcrumb">
    <button type="button" class="run-breadcrumb__item" @click="emit('locate', 'mission')">{{ props.missionTitle }}</button>
    <button type="button" class="run-breadcrumb__item" @click="emit('locate', 'run')">Run 01</button>
    <template v-if="props.items.length">
      <template v-for="(item, index) in props.items" :key="item.id">
        <button type="button" class="run-breadcrumb__item" :class="{ 'is-current': index === items.length - 1 }" @click="emit('locate', item.id)">{{ item.title }}</button>
      </template>
    </template>
  </nav>
</template>

<script setup lang="ts">
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'

const props = withDefaults(defineProps<{
  missionTitle: string
  items?: RunDocumentSymbol[]
}>(), {
  items: () => []
})

const emit = defineEmits<{ locate: [symbolId: string] }>()
</script>

<style scoped>
.run-breadcrumb { display: flex; align-items: center; min-width: 0; gap: 10px; margin-bottom: 13px; overflow-x: auto; scrollbar-width: none; white-space: nowrap; }
.run-breadcrumb::-webkit-scrollbar { display: none; }
.run-breadcrumb__item { max-width: 230px; overflow: hidden; padding: 0; border: 0; color: var(--wb-text-muted); background: transparent; cursor: pointer; font: 12px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.run-breadcrumb__item:hover, .run-breadcrumb__item:focus-visible { color: var(--wb-accent); }
.run-breadcrumb__item.is-current { color: var(--wb-text-secondary); }
.run-breadcrumb__item:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 2px; }
</style>
