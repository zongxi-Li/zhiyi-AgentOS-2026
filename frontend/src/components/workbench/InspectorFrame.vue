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
.inspector-frame { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; color: var(--text-primary); background: var(--bg-card); }
.inspector-frame__header { display: flex; justify-content: space-between; gap: 12px; padding: 16px 15px 13px; border-bottom: 1px solid var(--border-light); }
.inspector-frame__header span:first-child { display: block; color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.inspector-frame__header strong { display: block; max-width: 210px; margin-top: 4px; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.inspector-frame__badge { align-self: flex-start; color: var(--warning); font: 10px var(--font-mono, monospace); }
.inspector-frame__body { min-height: 0; overflow: auto; }
</style>
