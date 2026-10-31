<template>
  <section v-if="items.length" aria-label="正式任务工具审批">
    <article v-for="item in items" :key="item.approvalId">
      <strong>确认任务文件或测试操作</strong>
      <p>{{ item.operationSummary }}</p>
      <code>{{ item.relativePath }}</code>
      <pre v-if="item.command">{{ item.command }}</pre>
      <p v-if="item.riskNotice">{{ item.riskNotice }}</p>
      <button :disabled="busy" @click="resolve(item.approvalId, 'allow_once')">允许本次操作</button>
      <button :disabled="busy" @click="resolve(item.approvalId, 'deny')">拒绝本次操作</button>
    </article>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<script setup lang="ts">
import { ref, onActivated, onDeactivated, onMounted, onUnmounted, watch } from 'vue'
import { agentosRequest } from '@/services/api/agentos/client'
const props = defineProps<{runId: string; active: boolean}>()
const items = ref<any[]>([])
const busy = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let viewActive = true
let generation = 0
async function refresh() {
  if (!viewActive) return
  if (!props.active || !props.runId) { items.value = []; return }
  const token = generation, runId = props.runId
  try {
    const response = await agentosRequest.get(`/runs/${encodeURIComponent(runId)}/tool-approvals`)
    if (viewActive && token === generation && runId === props.runId) items.value = response.data.items
  }
  catch { /* existing Runtime status reports disconnects; never auto-approve */ }
}
async function resolve(id: string, decision: string) {
  busy.value = true
  error.value = ''
  try {
    await agentosRequest.post(`/runs/${encodeURIComponent(props.runId)}/tool-approvals/${encodeURIComponent(id)}`, { decision })
    await refresh()
  } catch { error.value = '操作审批失败，请刷新状态。' }
  finally { busy.value = false }
}
const start = () => { if (timer) clearInterval(timer); void refresh(); timer = setInterval(() => void refresh(), 1000) }
const stop = () => { ++generation; if (timer) clearInterval(timer); timer = undefined }
onMounted(start)
onDeactivated(() => { viewActive = false; stop() })
onActivated(() => { if (viewActive) return; viewActive = true; start() })
onUnmounted(stop)
watch(() => [props.runId,props.active], () => { ++generation; void refresh() })
</script>
<style scoped>
article { margin: 8px 0; padding: 10px; border: 1px solid var(--wb-border-soft); border-radius: 6px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 120px; overflow: auto; }
button { margin: 6px 8px 0 0; }
</style>
