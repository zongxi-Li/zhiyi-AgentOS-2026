<template>
  <div class="inspector-header-actions" aria-label="Inspector controls">
    <button
      type="button"
      class="inspector-header-actions__button"
      :aria-label="fullscreen ? '退出 Inspector 全屏' : 'Inspector 全屏'"
      :title="fullscreen ? '退出全屏' : '全屏'"
      @click="emit('toggleFullscreen')"
    >
      <el-icon><FullScreen /></el-icon>
    </button>
    <button
      type="button"
      class="inspector-header-actions__button"
      aria-label="关闭 Inspector"
      title="关闭 Inspector"
      @click="emit('close')"
    >
      <el-icon><Close /></el-icon>
    </button>
  </div>
</template>

<script setup lang="ts">
import { Close, FullScreen } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  fullscreen?: boolean
}>(), {
  fullscreen: false
})

const emit = defineEmits<{
  close: []
  toggleFullscreen: []
}>()
</script>

<style scoped>
.inspector-header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 3px; }
.inspector-header-actions__button {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--wb-radius-sm);
  color: var(--wb-text-muted);
  background: transparent;
  cursor: pointer;
  font-size: 15px;
  transition: color 140ms var(--ease-out), border-color 140ms var(--ease-out), background-color 140ms var(--ease-out);
}
.inspector-header-actions__button:hover { border-color: color-mix(in srgb, var(--wb-accent) 28%, var(--wb-border)); color: var(--wb-text); background: var(--wb-hover); }
.inspector-header-actions__button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 1px; }
</style>
