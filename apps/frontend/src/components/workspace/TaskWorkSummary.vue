<template>
  <section v-if="ongoing" class="task-work-summary" aria-label="步骤思路与模型进展">
    <template v-if="objective || rationale">
      <p class="task-work-summary__label">本步骤的处理思路 <small>来自已确认规划</small></p>
      <p v-if="objective">{{ objective }}</p>
      <p v-if="rationale && rationale !== objective">{{ rationale }}</p>
    </template>
    <p class="task-work-summary__activity" role="status">{{ activity }}<span v-if="waitingSeconds != null"> · 已等待 {{ waitingSeconds }} 秒</span></p>
  </section>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import type { NodeRuntimeState } from '@/workbench/runtime/runtimeEvents'

const props = defineProps<{ node: NodeRuntimeState; objective?: string | null; rationale?: string | null }>()
const now = ref(Date.now())
const ongoing = computed(() => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(props.node.status))
const waiting = computed(() => ongoing.value && !props.node.firstTokenAt && !props.node.chunkCount && props.node.phase !== 'FINALIZING')
const waitingSeconds = computed(() => {
  if (!waiting.value || !props.node.modelStartedAt) return null
  const start = Date.parse(props.node.modelStartedAt)
  return Number.isFinite(start) ? Math.max(0, Math.floor((now.value - start) / 1000)) : null
})
const activity = computed(() => {
  if (props.node.phase === 'FINALIZING') return '正文已返回，正在校验步骤结果。'
  if (props.node.firstTokenAt || props.node.chunkCount) return '已收到模型正文，正在持续生成。'
  if (props.node.lastActivityAt) return '已收到模型活动信号，正文尚未返回。'
  return props.node.modelStartedAt ? '模型请求已发出，正在等待正文。' : '步骤已开始，正在准备模型请求。'
})
let timer: ReturnType<typeof setInterval> | undefined
let suspended = false
function stopClock() { if (timer) clearInterval(timer); timer = undefined }
function updateClock() {
  stopClock()
  now.value = Date.now()
  if (!suspended && waiting.value && props.node.modelStartedAt) timer = setInterval(() => { now.value = Date.now() }, 1000)
}
watch(() => [waiting.value, props.node.modelStartedAt], updateClock, { immediate: true })
onDeactivated(() => { suspended = true; stopClock() })
onActivated(() => { suspended = false; updateClock() })
onBeforeUnmount(stopClock)
</script>

<style scoped>
.task-work-summary { min-width: 0; margin: 0 0 18px; color: var(--wb-text-secondary); font-size: 13px; line-height: 1.75; overflow-wrap: anywhere; text-wrap: pretty; }
.task-work-summary p { margin: 0 0 8px; }
.task-work-summary .task-work-summary__label, .task-work-summary .task-work-summary__activity { color: var(--wb-text-muted); font-size: 11px; }
.task-work-summary__label small { margin-left: 8px; font-size: 10px; }
.task-work-summary .task-work-summary__activity { margin-bottom: 0; }
</style>
