<template>
  <section
    ref="containerRef"
    class="workbench-layout"
    :class="{
      'is-resizing': Boolean(resizingSide),
      'is-left-collapsed': !leftPaneVisible,
      'is-right-collapsed': !rightPaneVisible
    }"
    :style="{
      '--workbench-left-width': `${leftPaneWidth}px`,
      '--workbench-right-width': `${effectiveRightPaneWidth}px`
    }"
  >
    <aside v-if="leftPaneVisible" class="workbench-pane workbench-pane--left" aria-label="ACG 任务导航">
      <slot name="left" />
    </aside>

    <ResizeHandle
      v-if="leftPaneVisible || leftAutoHidden"
      side="left"
      :value="leftPaneWidth"
      :min="LEFT_MIN_WIDTH"
      :max="leftMaxWidth"
      :ariaLabel="leftAutoHidden ? '拖动恢复左侧任务导航并调整宽度' : '调整左侧任务导航宽度'"
      @resize-start="startResize('left', $event)"
      @resize-keydown="handleResizeKeydown('left', $event)"
      @reset="resetWidth('left')"
    />

    <main class="workbench-pane workbench-pane--main">
      <slot
        name="main"
        :left-auto-hidden="leftAutoHidden"
        :right-auto-hidden="rightAutoHidden"
        :right-enabled="rightEnabled"
      />
    </main>

    <ResizeHandle
      v-if="rightPaneVisible || rightAutoHidden"
      side="right"
      :value="effectiveRightPaneWidth"
      :min="RIGHT_MIN_WIDTH"
      :max="rightMaxForHandle"
      :ariaLabel="rightAutoHidden ? '拖动恢复右侧运行详情并调整宽度' : '调整右侧运行详情宽度'"
      @resize-start="startResize('right', $event)"
      @resize-keydown="handleResizeKeydown('right', $event)"
      @reset="resetWidth('right')"
    />

    <aside v-if="rightPaneVisible" class="workbench-pane workbench-pane--right" aria-label="ACG 运行详情">
      <slot name="right" />
    </aside>
  </section>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import ResizeHandle from './ResizeHandle.vue'
import { useWorkbenchLayout } from '@/composables/useWorkbenchLayout'

const props = withDefaults(defineProps<{
  showRight?: boolean
  storageKey?: string
}>(), {
  showRight: true,
  storageKey: 'zhiyi.acg.workbench.layout.v1'
})

const layout = useWorkbenchLayout({
  storageKey: props.storageKey,
  rightEnabled: toRef(props, 'showRight')
})

const {
  containerRef,
  leftPaneWidth,
  effectiveRightPaneWidth,
  rightMaxWidth,
  leftAutoHidden,
  rightAutoHidden,
  rightEnabled,
  resizingSide,
  leftPaneVisible,
  rightPaneVisible,
  startResize,
  handleResizeKeydown,
  resetWidth
} = layout

const LEFT_MIN_WIDTH = 240
const RIGHT_MIN_WIDTH = 300
const leftMaxWidth = computed(() => {
  const available = layout.containerWidth.value - 560 - (rightPaneVisible.value ? effectiveRightPaneWidth.value + 8 : 0) - 8
  return Math.max(LEFT_MIN_WIDTH, Math.min(520, available > 0 ? available : 520))
})
const rightMaxForHandle = computed(() => {
  const available = layout.containerWidth.value - 560 - (leftPaneVisible.value ? leftPaneWidth.value + 8 : 0) - 8
  return Math.max(RIGHT_MIN_WIDTH, Math.min(rightMaxWidth.value, available > 0 ? available : rightMaxWidth.value))
})
</script>

<style scoped>
.workbench-layout {
  --wb-bg: var(--bg-app, #f7f8fc);
  --wb-sidebar-bg: var(--bg-card, #fff);
  --wb-editor-bg: var(--bg-card, #fff);
  --wb-panel-bg: var(--bg-card, #fff);
  --wb-border: var(--border-light, #e5e7ef);
  --wb-hover: var(--bg-input, #f3f4f8);
  --wb-active: var(--primary-fade, #f0edff);
  --wb-muted: var(--text-secondary, #73798c);
  --wb-text: var(--text-primary, #25283a);
  --wb-accent: var(--primary-color, #7562e8);
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--wb-bg);
}

.workbench-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: flex-basis 180ms var(--ease-out), width 180ms var(--ease-out), opacity 180ms var(--ease-out);
}

.workbench-pane--left {
  flex: 0 0 var(--workbench-left-width);
  width: var(--workbench-left-width);
  background: var(--wb-sidebar-bg);
}

.workbench-pane--main {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: auto;
}

.workbench-pane--right {
  flex: 0 0 var(--workbench-right-width);
  width: var(--workbench-right-width);
  background: var(--wb-sidebar-bg);
}

.workbench-layout.is-resizing .workbench-pane {
  transition: none;
}

@media (prefers-reduced-motion: reduce) {
  .workbench-pane { transition-duration: 1ms; }
}
</style>
