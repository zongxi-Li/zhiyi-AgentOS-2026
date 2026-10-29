<template>
  <div
    v-if="isDesktopRuntime && status !== 'online'"
    class="desktop-runtime-status"
    :class="`is-${status}`"
    role="status"
    aria-live="polite"
  >
    <span class="status-dot" aria-hidden="true" />
    <div class="status-copy">
      <strong>{{ statusTitle }}</strong>
      <span>{{ statusMessage }}</span>
    </div>
    <button v-if="status !== 'checking'" type="button" @click="retry">重试</button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { checkRuntimeStatus, isDesktop, type RuntimeStatus } from '@/platform'

const isDesktopRuntime = isDesktop()
const status = ref<RuntimeStatus>('checking')
let controller: AbortController | null = null

const statusTitle = computed(() => {
  if (status.value === 'checking') return '正在检查 Runtime'
  if (status.value === 'unknown') return 'Runtime 状态未知'
  return 'AgentOS Runtime Offline'
})

const statusMessage = computed(() => {
  if (status.value === 'checking') return '正在连接本地 Backend…'
  if (status.value === 'unknown') return 'Backend 返回了无法识别的健康状态。'
  return '本地 AgentOS Runtime 当前不可用。'
})

const check = async () => {
  controller?.abort()
  controller = new AbortController()
  try {
    status.value = 'checking'
    status.value = await checkRuntimeStatus(controller.signal)
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) status.value = 'offline'
  }
}

const retry = () => { void check() }

onMounted(() => {
  if (isDesktopRuntime) void check()
})

onUnmounted(() => controller?.abort())
</script>

<style scoped>
.desktop-runtime-status {
  position: fixed;
  top: 14px;
  right: 18px;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: min(430px, calc(100vw - 36px));
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--warning, #e6a23c) 45%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-card, #fff) 94%, var(--warning, #e6a23c));
  color: var(--text-primary, #1f2937);
  box-shadow: 0 8px 24px rgb(15 23 42 / 12%);
}

.desktop-runtime-status.is-offline {
  border-color: color-mix(in srgb, var(--danger, #f56c6c) 48%, transparent);
  background: color-mix(in srgb, var(--bg-card, #fff) 94%, var(--danger, #f56c6c));
}

.status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: var(--warning, #e6a23c);
}

.is-offline .status-dot { background: var(--danger, #f56c6c); }

.status-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
  font-size: 12px;
}

.status-copy strong { font-size: 13px; }
.status-copy span { color: var(--text-secondary, #64748b); }

.desktop-runtime-status button {
  flex: 0 0 auto;
  padding: 4px 9px;
  border: 1px solid currentColor;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 12px;
}
</style>
