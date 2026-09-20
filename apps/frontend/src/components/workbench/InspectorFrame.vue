<template>
  <div class="inspector-frame">
    <header class="inspector-frame__header">
      <div>
        <span>INSPECTOR</span>
        <strong>{{ title }}</strong>
      </div>
      <div class="inspector-frame__actions">
        <span v-if="historical" class="inspector-frame__badge">Historical</span>
        <InspectorHeaderActions
          :fullscreen="fullscreen"
          @toggle-fullscreen="emit('toggleFullscreen')"
          @close="emit('close')"
        />
      </div>
    </header>
    <div class="inspector-frame__body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import InspectorHeaderActions from './InspectorHeaderActions.vue'

defineProps<{
  title: string
  historical?: boolean
  fullscreen?: boolean
}>()

const emit = defineEmits<{
  close: []
  toggleFullscreen: []
}>()
</script>

<style scoped>
.inspector-frame { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; color: var(--wb-text); background: var(--wb-surface-pane); }
.inspector-frame__header { display: flex; justify-content: space-between; gap: 12px; padding: 13px 15px 12px; border-bottom: 0; background: var(--wb-surface-pane); }
.inspector-frame__actions { display: flex; flex: 0 0 auto; align-items: flex-start; gap: 7px; }
.inspector-frame__header span:first-child { display: block; color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }
.inspector-frame__header strong { display: -webkit-box; max-width: min(280px, 100%); margin-top: 4px; overflow: hidden; font-size: 14px; font-weight: 700; line-height: 1.35; text-overflow: ellipsis; white-space: normal; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.inspector-frame__badge { align-self: flex-start; padding: 3px 6px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-warning); font: 10px var(--font-mono, monospace); }
.inspector-frame__body { min-height: 0; overflow: auto; padding: 0 14px 18px; background: var(--wb-surface-1); scrollbar-gutter: stable; }
.inspector-frame__body :deep(.inspector-section) { margin-bottom: 10px; }
.inspector-frame__body :deep(.inspector-section:last-child) { margin-bottom: 0; }
</style>
