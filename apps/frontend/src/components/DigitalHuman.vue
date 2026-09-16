<template>
  <div
    class="digital-human-container is-frozen"
    aria-label="数字人功能已冻结"
  >
    <div class="digital-human-fallback">
      <el-icon aria-hidden="true"><UserFilled /></el-icon>
      <span>数字人功能已冻结</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { UserFilled } from '@element-plus/icons-vue'

interface Props {
  roleId?: string
  avatarId?: string
  isSpeaking?: boolean
  audioUrl?: string
  style?: string
  transparent?: boolean
}

// Keep the existing public props so callers remain compatible while the
// renderer and its network/animation work are intentionally paused.
withDefaults(defineProps<Props>(), {
  isSpeaking: false,
  style: 'realistic',
  transparent: false
})
</script>

<style scoped>
.digital-human-container {
  width: 100%;
  height: 100%;
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  color: var(--text-secondary, #64748b);
}

.digital-human-fallback {
  display: grid;
  place-items: center;
  gap: 8px;
  padding: 20px;
  font-size: 12px;
  line-height: 1.5;
  text-align: center;
}

.digital-human-fallback :deep(.el-icon) {
  font-size: 28px;
  color: var(--text-disabled, #94a3b8);
}
</style>
