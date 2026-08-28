<template>
  <section
    ref="splitRef"
    class="workbench-vertical-split"
    :class="{ 'is-resizing': resizing, 'is-collapsed': collapsed }"
    :style="{ '--workbench-bottom-panel-height': `${collapsed ? COLLAPSED_HEIGHT : panelHeight}px` }"
  >
    <div class="workbench-vertical-split__graph-pane">
      <slot name="graph" />
    </div>

    <HorizontalResizeHandle
      v-if="!collapsed"
      :value="panelHeight"
      :min="minHeight"
      :max="maxHeight"
      :dragging="resizing"
      ariaLabel="调整图表与运行面板高度"
      @resize-start="startResize"
      @resize-move="handlePointerMove"
      @resize-end="stopResize"
      @resize-keydown="handleResizeKeydown"
      @reset="resetHeight"
    />

    <div class="workbench-vertical-split__bottom-panel">
      <slot
        name="bottom"
        :collapsed="collapsed"
        :set-collapsed="setCollapsed"
        :toggle-collapsed="toggleCollapsed"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import HorizontalResizeHandle from './HorizontalResizeHandle.vue'
import {
  readWorkbenchLayoutPersistence,
  writeWorkbenchLayoutPersistence
} from '@/composables/useWorkbenchLayout'

const COLLAPSED_HEIGHT = 34
const HANDLE_HEIGHT = 7

const props = withDefaults(defineProps<{
  storageKey?: string
  defaultHeight?: number
  minHeight?: number
  maxHeightRatio?: number
  minGraphHeight?: number
}>(), {
  storageKey: 'zhiyi.acg.workbench.layout.v1',
  defaultHeight: 260,
  minHeight: 120,
  maxHeightRatio: 0.65,
  minGraphHeight: 280
})

const persisted = readWorkbenchLayoutPersistence(props.storageKey)
const splitRef = ref<HTMLElement | null>(null)
const splitHeight = ref(0)
const fallbackHeight = typeof window === 'undefined' ? 720 : window.innerHeight
const fallbackMaxHeight = Math.max(
  props.minHeight,
  Math.min(
    Math.floor(fallbackHeight * props.maxHeightRatio),
    fallbackHeight - props.minGraphHeight - HANDLE_HEIGHT
  )
)
const panelHeight = ref(Math.min(
  fallbackMaxHeight,
  Math.max(props.minHeight, Math.round(persisted.bottomPanelHeight ?? props.defaultHeight))
))
const internalCollapsed = ref(persisted.bottomPanelCollapsedByUser ?? false)
const resizing = ref(false)
let resizeObserver: ResizeObserver | null = null
let resizeFrame: number | null = null
let pendingHeight: number | null = null
let resizeStartY = 0
let resizeStartHeight = 0
let previousBodyCursor = ''
let previousBodyUserSelect = ''

const collapsed = computed(() => internalCollapsed.value)
const availableHeight = computed(() => splitHeight.value || (typeof window === 'undefined' ? 720 : window.innerHeight))
const maxHeight = computed(() => Math.max(
  props.minHeight,
  Math.min(
    Math.floor(availableHeight.value * props.maxHeightRatio),
    availableHeight.value - props.minGraphHeight - HANDLE_HEIGHT
  )
))

const clampHeight = (value: number) => Math.min(maxHeight.value, Math.max(props.minHeight, Math.round(value)))

const persist = (patch: { bottomPanelHeight?: number; bottomPanelCollapsedByUser?: boolean }) => {
  writeWorkbenchLayoutPersistence(props.storageKey, patch)
}

const syncSplitHeight = () => {
  splitHeight.value = splitRef.value?.clientHeight || 0
  panelHeight.value = clampHeight(panelHeight.value)
}

const cancelResizeFrame = () => {
  if (resizeFrame === null) return
  if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(resizeFrame)
  } else if (typeof window !== 'undefined') {
    window.clearTimeout(resizeFrame)
  }
  resizeFrame = null
}

const applyPendingHeight = () => {
  resizeFrame = null
  if (pendingHeight === null) return
  panelHeight.value = clampHeight(pendingHeight)
  pendingHeight = null
}

const scheduleHeight = (height: number) => {
  pendingHeight = height
  if (resizeFrame !== null) return
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    resizeFrame = window.requestAnimationFrame(applyPendingHeight)
  } else if (typeof window !== 'undefined') {
    resizeFrame = window.setTimeout(applyPendingHeight, 16)
  }
}

const startResize = (event: PointerEvent) => {
  if (resizing.value) return
  resizeStartY = event.clientY
  resizeStartHeight = panelHeight.value
  resizing.value = true
  previousBodyCursor = document.body.style.cursor
  previousBodyUserSelect = document.body.style.userSelect
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
}

const handlePointerMove = (event: PointerEvent) => {
  if (!resizing.value) return
  const delta = resizeStartY - event.clientY
  scheduleHeight(clampHeight(resizeStartHeight + delta))
}

const stopResize = () => {
  if (!resizing.value) return
  cancelResizeFrame()
  applyPendingHeight()
  resizing.value = false
  pendingHeight = null
  document.body.style.cursor = previousBodyCursor
  document.body.style.userSelect = previousBodyUserSelect
  persist({ bottomPanelHeight: panelHeight.value })
}

const adjustHeight = (delta: number) => {
  panelHeight.value = clampHeight(panelHeight.value + delta)
  persist({ bottomPanelHeight: panelHeight.value })
}

const handleResizeKeydown = (event: KeyboardEvent) => {
  const step = event.shiftKey ? 48 : 16
  if (event.key === 'Home') panelHeight.value = props.minHeight
  else if (event.key === 'End') panelHeight.value = maxHeight.value
  else if (event.key === 'ArrowUp') adjustHeight(step)
  else if (event.key === 'ArrowDown') adjustHeight(-step)
  else return
  persist({ bottomPanelHeight: panelHeight.value })
  event.preventDefault()
}

const resetHeight = () => {
  panelHeight.value = clampHeight(props.defaultHeight)
  persist({ bottomPanelHeight: panelHeight.value })
}

const setCollapsed = (value: boolean) => {
  internalCollapsed.value = value
  persist({ bottomPanelCollapsedByUser: value })
}

const toggleCollapsed = () => setCollapsed(!collapsed.value)

onMounted(() => {
  syncSplitHeight()
  if (typeof ResizeObserver !== 'undefined' && splitRef.value) {
    resizeObserver = new ResizeObserver(syncSplitHeight)
    resizeObserver.observe(splitRef.value)
  }
})

onBeforeUnmount(() => {
  cancelResizeFrame()
  if (resizing.value) {
    document.body.style.cursor = previousBodyCursor
    document.body.style.userSelect = previousBodyUserSelect
  }
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<style scoped>
.workbench-vertical-split {
  --workbench-bottom-panel-height: 260px;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.workbench-vertical-split__graph-pane {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.workbench-vertical-split__bottom-panel {
  flex: 0 0 var(--workbench-bottom-panel-height);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.workbench-vertical-split__bottom-panel > :deep(.workbench-bottom-panel) {
  width: 100%;
  height: 100%;
}

.workbench-vertical-split.is-resizing .workbench-vertical-split__bottom-panel,
.workbench-vertical-split.is-resizing .workbench-vertical-split__bottom-panel :deep(*) {
  transition: none !important;
}
</style>
