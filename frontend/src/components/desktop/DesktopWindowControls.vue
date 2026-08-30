<template>
  <div class="desktop-window-controls">
    <button type="button" class="dwc-button" aria-label="最小化" title="最小化" @click="minimize">
      <svg class="dwc-icon" width="14" height="14" viewBox="0 0 14 14" shape-rendering="crispEdges" aria-hidden="true">
        <path d="M2 7h10" />
      </svg>
    </button>
    <button
      type="button"
      class="dwc-button"
      :aria-label="maximized ? '向下还原' : '最大化'"
      :title="maximized ? '向下还原' : '最大化'"
      @click="toggleMaximize"
    >
      <svg v-if="!maximized" class="dwc-icon" width="14" height="14" viewBox="0 0 14 14" shape-rendering="crispEdges" aria-hidden="true">
        <rect x="2.5" y="2.5" width="9" height="9" />
      </svg>
      <svg v-else class="dwc-icon" width="14" height="14" viewBox="0 0 14 14" shape-rendering="crispEdges" aria-hidden="true">
        <rect x="2.5" y="4.5" width="7" height="7" />
        <path d="M4.5 4.5v-2h7v7h-2" />
      </svg>
    </button>
    <button type="button" class="dwc-button dwc-button--close" aria-label="关闭" title="关闭" @click="closeWindow">
      <svg class="dwc-icon" width="14" height="14" viewBox="0 0 14 14" shape-rendering="crispEdges" aria-hidden="true">
        <path d="m3 3 8 8M11 3l-8 8" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'

// 只负责窗口本体：最小化 / 最大化 / 还原 / 关闭 / 真实窗口状态同步。
// 不感知 Mission、Run、ACG、Chat、API、Auth 等任何业务概念。
const maximized = ref(false)
const appWindow = getCurrentWindow()
let unlistenResized: (() => void) | null = null

// 图标跟随真实窗口状态（Win+↑、Snap、边缘拖动、系统还原都会触发 resize 事件）。
const syncMaximizedState = async (): Promise<void> => {
  try {
    maximized.value = await appWindow.isMaximized()
  } catch {
    // 窗口句柄暂不可用时保持上一状态，不打断用户。
  }
}

onMounted(() => {
  void syncMaximizedState()
  void appWindow.onResized(() => {
    void syncMaximizedState()
  }).then((unlisten) => {
    unlistenResized = unlisten
  })
})

onBeforeUnmount(() => {
  unlistenResized?.()
})

const minimize = (): void => {
  void appWindow.minimize()
}

const toggleMaximize = (): void => {
  void appWindow.toggleMaximize()
}

const closeWindow = (): void => {
  void appWindow.close()
}
</script>

<style scoped>
.desktop-window-controls {
  display: flex;
  align-items: stretch;
  height: 100%;
}

.dwc-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 100%;
  padding: 0;
  color: var(--app-topbar-muted, var(--text-secondary, #737991));
  background: transparent;
  border: 0;
  border-radius: 0;
  cursor: default;
  outline-offset: -2px;
  transition: background-color 120ms ease, color 120ms ease;
}

.dwc-button:hover {
  background: var(--app-topbar-hover, rgba(0, 0, 0, 0.05));
}

.dwc-button:active {
  background: var(--app-topbar-active, rgba(0, 0, 0, 0.08));
}

.dwc-button:focus-visible {
  outline: 2px solid var(--app-topbar-focus-ring, rgba(167, 139, 250, 0.3));
}

.dwc-icon {
  fill: none;
  stroke: currentColor;
  stroke-width: 1;
}

.dwc-button--close:hover {
  color: #ffffff;
  background: color-mix(in srgb, #c42b1c 85%, #ffffff);
}

.dwc-button--close:active {
  color: #ffffff;
  background: #c42b1c;
}

@media (prefers-reduced-motion: reduce) {
  .dwc-button {
    transition: none;
  }
}
</style>
