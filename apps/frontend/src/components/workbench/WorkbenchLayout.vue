<template>
  <section
    ref="containerRef"
    class="workbench-layout"
    :class="{
      'is-resizing': Boolean(resizingSide),
      'is-left-collapsed': !leftVisible,
      'is-right-collapsed': !rightPaneVisible
    }"
    :style="{
      '--workbench-left-width': `${leftPaneWidth}px`,
      '--workbench-right-width': `${effectiveRightPaneWidth}px`
    }"
  >
    <aside v-if="leftVisible" class="workbench-pane workbench-pane--left" aria-label="项目导航">
      <slot name="left" />
    </aside>

    <ResizeHandle
      v-if="showLeft && (leftPaneVisible || leftAutoHidden)"
      side="left"
      :value="leftPaneWidth"
      :min="LEFT_MIN_WIDTH"
      :max="leftMaxWidth"
      :ariaLabel="leftAutoHidden ? '拖动或单击恢复左侧任务导航并调整宽度' : '调整左侧任务导航宽度'"
      @resize-start="startResize('left', $event)"
      @resize-keydown="handleResizeKeydown('left', $event)"
      @reset="resetWidth('left')"
      @click="leftAutoHidden && restoreLeftPane()"
    />

    <main class="workbench-pane workbench-pane--main">
      <WorkbenchVerticalSplit
        v-if="showBottomPanel"
        :storage-key="bottomPanelStorageKey"
        :default-collapsed="bottomPanelDefaultCollapsed"
      >
        <template #graph>
          <slot
            name="main"
            :left-auto-hidden="leftAutoHidden"
            :restore-left-pane="restoreLeftPane"
            :right-auto-hidden="rightAutoHidden"
            :right-enabled="rightEnabled"
            :right-pane-visible="rightPaneVisible"
            :right-collapsed-by-user="rightCollapsedByUser"
            :toggle-right-pane="toggleRightPane"
          />
        </template>
        <template #bottom="bottomState">
          <slot name="bottom" v-bind="bottomState" />
        </template>
      </WorkbenchVerticalSplit>
        <slot
          v-else
          name="main"
          :left-auto-hidden="leftAutoHidden"
          :restore-left-pane="restoreLeftPane"
          :right-auto-hidden="rightAutoHidden"
          :right-enabled="rightEnabled"
          :right-pane-visible="rightPaneVisible"
          :right-collapsed-by-user="rightCollapsedByUser"
          :toggle-right-pane="toggleRightPane"
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
import WorkbenchVerticalSplit from './WorkbenchVerticalSplit.vue'
import { useWorkbenchLayout } from '@/composables/useWorkbenchLayout'

const props = withDefaults(defineProps<{
  showLeft?: boolean
  showRight?: boolean
  showBottomPanel?: boolean
  bottomPanelStorageKey?: string
  bottomPanelDefaultCollapsed?: boolean
  storageKey?: string
}>(), {
  showLeft: true,
  showRight: true,
  showBottomPanel: false,
  bottomPanelStorageKey: 'zhiyi.workbench.bottom-panel.v1',
  bottomPanelDefaultCollapsed: false,
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
  rightCollapsedByUser,
  rightEnabled,
  resizingSide,
  leftPaneVisible,
  rightPaneVisible,
  toggleRightPane,
  restoreLeftPane,
  startResize,
  handleResizeKeydown,
  resetWidth
} = layout

const leftVisible = computed(() => props.showLeft && leftPaneVisible.value)

const LEFT_MIN_WIDTH = 240
const RIGHT_MIN_WIDTH = 300
const leftMaxWidth = computed(() => {
  const available = layout.containerWidth.value - 560 - (rightPaneVisible.value ? effectiveRightPaneWidth.value + 8 : 0) - 8
  return Math.max(LEFT_MIN_WIDTH, Math.min(520, available > 0 ? available : 520))
})
const rightMaxForHandle = computed(() => {
  const available = layout.containerWidth.value - 560 - (leftVisible.value ? leftPaneWidth.value + 8 : 0) - 8
  return Math.max(RIGHT_MIN_WIDTH, Math.min(rightMaxWidth.value, available > 0 ? available : rightMaxWidth.value))
})
</script>

<style scoped>
.workbench-layout {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--wb-surface-0);
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
  border-right: 1px solid var(--wb-border);
  background: var(--wb-surface-1);
}

.workbench-pane--main {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: auto;
}

.workbench-pane--right {
  flex: 0 0 var(--workbench-right-width);
  width: var(--workbench-right-width);
  border-left: 1px solid var(--wb-border);
  background: var(--wb-surface-1);
}

.workbench-layout.is-resizing .workbench-pane {
  transition: none;
}

@media (prefers-reduced-motion: reduce) {
  .workbench-pane { transition-duration: 1ms; }
}
</style>
