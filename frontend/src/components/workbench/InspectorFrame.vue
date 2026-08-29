<template>
  <div class="inspector-frame">
    <header class="inspector-frame__header">
      <div>
        <span>INSPECTOR</span>
        <strong>{{ title }}</strong>
      </div>
      <span v-if="historical" class="inspector-frame__badge">Historical</span>
    </header>
    <div class="inspector-frame__body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  historical?: boolean
}>()
</script>

<style scoped>
.inspector-frame { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; color: var(--wb-text); background: var(--wb-surface-pane); }
.inspector-frame__header { display: flex; justify-content: space-between; gap: 12px; padding: 13px 15px 12px; border-bottom: 1px solid var(--wb-border-soft); background: var(--wb-surface-pane); }
.inspector-frame__header span:first-child { display: block; color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.inspector-frame__header strong { display: block; max-width: 240px; margin-top: 4px; overflow: hidden; font-size: 14px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.inspector-frame__badge { align-self: flex-start; padding: 3px 6px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-warning); font: 10px var(--font-mono, monospace); }
.inspector-frame__body { min-height: 0; overflow: auto; padding: 10px; background: var(--wb-surface-shell); scrollbar-gutter: stable; }
.inspector-frame__body :deep(.inspector-section) { margin-bottom: 10px; }
.inspector-frame__body :deep(.inspector-section:last-child) { margin-bottom: 0; }
</style>
