<template>
  <div
    class="workbench-horizontal-resize-handle"
    :class="{ 'is-dragging': dragging }"
    :data-dragging="dragging"
    role="separator"
    aria-orientation="horizontal"
    :aria-label="ariaLabel"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :aria-valuenow="value"
    :title="`${ariaLabel}，双击恢复默认`"
    tabindex="0"
    @pointerdown="handlePointerDown"
    @pointermove="emit('resize-move', $event)"
    @pointerup="handlePointerEnd"
    @pointercancel="handlePointerEnd"
    @lostpointercapture="emit('resize-end', $event)"
    @keydown="emit('resize-keydown', $event)"
    @dblclick="emit('reset')"
  ></div>
</template>

<script setup lang="ts">
defineProps<{
  value: number
  min: number
  max: number
  ariaLabel: string
  dragging?: boolean
}>()

const emit = defineEmits<{
  'resize-start': [event: PointerEvent]
  'resize-move': [event: PointerEvent]
  'resize-end': [event: PointerEvent]
  'resize-keydown': [event: KeyboardEvent]
  reset: []
}>()

const handlePointerDown = (event: PointerEvent) => {
  if (event.button !== 0) return
  event.preventDefault()
  const handle = event.currentTarget as HTMLElement | null
  if (handle?.setPointerCapture && event.pointerId !== undefined) {
    handle.setPointerCapture(event.pointerId)
  }
  emit('resize-start', event)
}

const handlePointerEnd = (event: PointerEvent) => {
  emit('resize-end', event)
  const handle = event.currentTarget as HTMLElement | null
  if (handle?.hasPointerCapture?.(event.pointerId)) handle.releasePointerCapture(event.pointerId)
}
</script>

<style scoped>
.workbench-horizontal-resize-handle {
  position: relative;
  z-index: 20;
  flex: 0 0 7px;
  width: 100%;
  min-height: 7px;
  cursor: row-resize;
  touch-action: none;
  pointer-events: auto;
  outline: none;
}

.workbench-horizontal-resize-handle::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 3px;
  height: 1px;
  background: var(--wb-border, var(--border-light));
  opacity: .7;
  transition: top 120ms ease, height 120ms ease, background-color 120ms ease, opacity 120ms ease;
}

.workbench-horizontal-resize-handle:hover::after,
.workbench-horizontal-resize-handle:focus-visible::after,
.workbench-horizontal-resize-handle.is-dragging::after {
  top: 2px;
  height: 2px;
  background: var(--wb-accent, var(--primary-color));
  opacity: 1;
}

.workbench-horizontal-resize-handle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--wb-accent, var(--primary-color)) 42%, transparent);
  outline-offset: -1px;
}
</style>
