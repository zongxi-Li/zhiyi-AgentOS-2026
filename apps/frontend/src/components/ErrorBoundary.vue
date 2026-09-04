<!-- 错误边界组件 — 捕获子组件渲染错误，显示全页错误提示和刷新按钮 -->
<template>
  <div v-if="hasError" class="error-boundary">
    <el-result
      icon="error"
      title="出现错误"
      sub-title="页面加载时出现错误，请刷新页面重试"
    >
      <template #extra>
        <el-button type="primary" @click="handleReset">刷新页面</el-button>
      </template>
    </el-result>
    <!-- 直接暴露异常摘要，方便桌面端用户截图即见根因 -->
    <p v-if="errorMessage" class="error-detail">{{ errorMessage }}</p>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'
import { ElMessage } from 'element-plus'

const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((err, instance, info) => {
  console.error('Error caught by boundary:', err, info)
  errorMessage.value = `${err instanceof Error ? err.message : String(err)}（${info}）`
  hasError.value = true
  ElMessage.error('页面出现错误，请刷新重试')
  return false
})

const handleReset = () => {
  window.location.reload()
}
</script>

<style scoped>
.error-boundary {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
}

.error-detail {
  max-width: 640px;
  margin: -12px auto 0;
  padding: 0 24px;
  color: var(--text-secondary, #909399);
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
  word-break: break-all;
}
</style>

