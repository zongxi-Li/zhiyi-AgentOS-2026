<template>
  <section v-if="runId" class="acg-entry-bridge" aria-live="polite">
    <div v-if="loading" class="acg-entry-bridge__card">
      <span class="acg-entry-bridge__eyebrow">MISSION PROJECT WORKSPACE</span>
      <h1>正在打开任务工作区</h1>
      <p>正在解析运行所属的 Mission…</p>
    </div>

    <div v-else class="acg-entry-bridge__card acg-entry-bridge__card--error" role="alert">
      <span class="acg-entry-bridge__eyebrow">WORKSPACE UNAVAILABLE</span>
      <h1>无法打开任务工作区</h1>
      <p>{{ errorMessage }}</p>
      <button type="button" @click="returnToAcgEntry">返回 ACG 任务入口</button>
    </div>
  </section>

  <LegacyAcgVisualization v-else />
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { workflowApi } from '@/services/api/workflow'

const LegacyAcgVisualization = defineAsyncComponent(() => import('./AcgVisualizationView.vue'))
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const errorMessage = ref('请稍后重试。')
let requestGeneration = 0
let requestController: AbortController | null = null

const runId = computed(() => {
  const value = route.query.runId
  return typeof value === 'string' ? value.trim() : ''
})

const returnToAcgEntry = () => {
  void router.replace({ path: '/agentos/acg', query: {} })
}

const openMissionWorkspace = async (targetRunId: string) => {
  const generation = ++requestGeneration
  requestController?.abort()
  requestController = new AbortController()
  loading.value = true
  errorMessage.value = '请稍后重试。'

  try {
    const run = await workflowApi.getRun(targetRunId, { signal: requestController.signal })
    if (generation !== requestGeneration || targetRunId !== runId.value) return
    if (!run.missionId?.trim()) {
      throw new Error('该运行记录缺少 missionId，无法建立 Mission Workspace。')
    }
    await router.replace({
      name: 'MissionWorkspace',
      params: { missionId: run.missionId },
      query: { runId: targetRunId }
    })
  } catch (error: any) {
    if (requestController?.signal.aborted || generation !== requestGeneration) return
    errorMessage.value = error?.response?.data?.detail || error?.message || '运行记录加载失败。'
    loading.value = false
  }
}

watch(runId, value => {
  if (value) {
    void openMissionWorkspace(value)
    return
  }
  requestGeneration += 1
  requestController?.abort()
  requestController = null
  loading.value = false
}, { immediate: true })

onBeforeUnmount(() => {
  requestGeneration += 1
  requestController?.abort()
})
</script>

<style scoped>
.acg-entry-bridge {
  min-height: 100%;
  display: grid;
  place-items: center;
  padding: 32px;
  background: #f7f8fc;
}

.acg-entry-bridge__card {
  width: min(520px, 100%);
  padding: 32px;
  border: 1px solid #e4e7f0;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 18px 48px rgb(33 42 78 / 10%);
}

.acg-entry-bridge__card--error {
  border-color: #f1d3d3;
}

.acg-entry-bridge__eyebrow {
  color: #6065d8;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .12em;
}

h1 {
  margin: 12px 0 8px;
  color: #20243a;
  font-size: 24px;
}

p {
  margin: 0;
  color: #73798f;
  line-height: 1.6;
}

button {
  margin-top: 24px;
  border: 0;
  border-radius: 8px;
  padding: 10px 16px;
  color: #fff;
  background: #5b60d6;
  cursor: pointer;
}
</style>
