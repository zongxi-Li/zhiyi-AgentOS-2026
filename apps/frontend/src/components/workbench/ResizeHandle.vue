<template>
  <div
    class="workbench-resize-handle"
    :class="`workbench-resize-handle--${side}`"
    role="separator"
    aria-orientation="vertical"
    :aria-label="ariaLabel"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :aria-valuenow="value"
    :title="`${ariaLabel}，双击恢复默认`"
    tabindex="0"
    @pointerdown="emit('resize-start', $event)"
    @keydown="emit('resize-keydown', $event)"
    @dblclick="emit('reset')"
  ></div>
</template>

<script setup lang="ts">
import type { WorkbenchPaneSide } from '@/composables/useWorkbenchLayout'

defineProps<{
  side: WorkbenchPaneSide
  value: number
  min: number
  max: number
  ariaLabel: string
}>()

const emit = defineEmits<{
  'resize-start': [event: PointerEvent]
  'resize-keydown': [event: KeyboardEvent]
  reset: []
}>()
</script>

<style scoped>
.workbench-resize-handle {
  position: relative;
  z-index: 2;
  flex: 0 0 8px;
  width: 8px;
  min-width: 8px;
  margin-inline: -4px;
  align-self: stretch;
  cursor: col-resize;
  touch-action: none;
  outline: none;
}

.workbench-resize-handle::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  transform: translateX(-50%);
  background: transparent;
  opacity: 0;
  transition: background-color 160ms ease, box-shadow 160ms ease, opacity 160ms ease;
}

.workbench-resize-handle:hover::after,
.workbench-resize-handle:focus-visible::after {
  background: var(--primary-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary-color) 18%, transparent);
  opacity: .9;
}

.workbench-resize-handle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--primary-color) 42%, transparent);
  outline-offset: -1px;
}

.workbench-layout.is-resizing .workbench-resize-handle::after {
  background: var(--primary-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary-color) 24%, transparent);
  opacity: 1;
}
</style>
