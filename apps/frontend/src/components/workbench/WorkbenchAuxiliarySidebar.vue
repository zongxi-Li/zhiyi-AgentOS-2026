<template>
  <aside class="auxiliary-sidebar" :aria-label="view.title">
    <header class="auxiliary-sidebar__header">
      <div class="auxiliary-sidebar__heading">
        <span>{{ view.title }}</span>
      </div>
    </header>
    <div class="auxiliary-sidebar__body">
      <component
        :is="view.component"
        v-bind="componentProps"
        @open-file="emit('open-file', $event)"
      />
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { AuxiliaryViewContribution } from '@/workbench/types'
import type { WorkspaceFileOpenRequest } from '@/services/api/agentos'

defineProps<{
  view: AuxiliaryViewContribution
  componentProps?: Record<string, unknown>
}>()

const emit = defineEmits<{
  'open-file': [request: WorkspaceFileOpenRequest]
}>()
</script>

<style scoped>
.auxiliary-sidebar {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  color: var(--wb-text);
  background: var(--wb-surface-1);
}
.auxiliary-sidebar__header {
  display: flex;
  min-height: 32px;
  align-items: center;
  padding: 0 12px;
  background: var(--wb-surface-1);
}
.auxiliary-sidebar__heading { min-width: 0; }
.auxiliary-sidebar__heading span {
  display: block;
  color: var(--wb-text-secondary);
  font: 12px/1 var(--font-sans, sans-serif);
  font-weight: 500;
}
.auxiliary-sidebar__body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  background: var(--wb-surface-1);
}
.auxiliary-sidebar__body :deep(.acg-copilot) {
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}
</style>
