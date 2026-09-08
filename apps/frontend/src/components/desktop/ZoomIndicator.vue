<template>
  <Transition name="ui-zoom-osd">
    <div v-if="uiZoomState.visible" class="ui-zoom-osd" role="group" aria-label="界面缩放">
      <button
        type="button"
        class="uzo-button"
        aria-label="缩小 (Ctrl+-)"
        title="缩小 (Ctrl+-)"
        @click="zoomOut"
      >
        <svg class="uzo-icon" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2 6h8" />
        </svg>
      </button>
      <button
        type="button"
        class="uzo-value"
        :aria-label="`当前缩放 ${percentage}%，点击复位 (Ctrl+0)`"
        :title="`缩放 ${percentage}% · 点击复位 100% (Ctrl+0)`"
        @click="resetZoom"
      >
        {{ percentage }}%
      </button>
      <button
        type="button"
        class="uzo-button"
        aria-label="放大 (Ctrl+=)"
        title="放大 (Ctrl+=)"
        @click="zoomIn"
      >
        <svg class="uzo-icon" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M6 2v8M2 6h8" />
        </svg>
      </button>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { uiZoomState, uiZoomPercentage, zoomIn, zoomOut, resetZoom } from '@/composables/useUiZoom'

// 桌面端 Ctrl+滚轮 / Ctrl± 缩放时的悬浮指示条：短暂显示、空闲自动隐藏，
// 档位状态与输入接管都在 useUiZoom，这里只做展示与鼠标操作入口。
const percentage = computed(() => uiZoomPercentage(uiZoomState.level))
</script>

<style scoped>
.ui-zoom-osd {
  position: fixed;
  left: 50%;
  bottom: 28px;
  transform: translateX(-50%);
  z-index: 6000;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border-radius: 999px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  box-shadow: var(--el-box-shadow-light);
  color: var(--el-text-color-primary);
  user-select: none;
}

.uzo-button,
.uzo-value {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: inherit;
}

.uzo-button {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  transition: background-color 0.15s ease;
}

.uzo-button:hover {
  background: var(--el-fill-color);
}

.uzo-icon {
  stroke: currentColor;
  stroke-width: 1.4;
  stroke-linecap: round;
  fill: none;
}

.uzo-value {
  min-width: 56px;
  height: 26px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  transition: background-color 0.15s ease;
}

.uzo-value:hover {
  background: var(--el-fill-color);
}

.ui-zoom-osd-enter-active,
.ui-zoom-osd-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.ui-zoom-osd-enter-from,
.ui-zoom-osd-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px);
}
</style>
