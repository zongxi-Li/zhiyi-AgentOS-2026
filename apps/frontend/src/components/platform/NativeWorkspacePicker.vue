<template>
  <div class="native-workspace" v-if="binding && route.path === '/chat'">
    <span :title="binding.workspaceRoot">{{ selected ? '工作目录已选择' : '已授权工作目录' }}：{{ binding.workspaceRoot }}</span>
    <button type="button" :disabled="busy" @click="choose">选择目录</button>
    <span v-if="error" role="alert">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { platform, apiUrl } from '@/platform'

type Binding = { workspaceRoot: string; workspaceId: string; grantId: string }
const binding = ref<Binding | null>(null)
const route = useRoute()
const selected = ref(false)
const busy = ref(false)
const error = ref('')
const headers = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || ''}`, 'Content-Type': 'application/json' })

onMounted(async () => {
  const response = await fetch(apiUrl('/ai/local-workspace'), { headers: headers() }).catch(() => null)
  if (response?.ok) binding.value = await response.json()
})

async function choose() {
  busy.value = true
  error.value = ''
  try {
    const path = await platform.openDirectory()
    if (!path) return
    const response = await fetch(apiUrl('/ai/local-workspace/select'), {
      method: 'POST', headers: headers(), body: JSON.stringify({ path })
    })
    if (!response.ok) throw new Error('该目录未在本次启动中授权，请使用 -Workspace 指定目录后重启原生服务。')
    binding.value = await response.json()
    selected.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '目录选择失败'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.native-workspace { display: flex; flex-shrink: 0; align-items: center; gap: 10px; min-width: 0; margin: 8px 18px; padding: 7px 10px; border: 1px solid var(--border-color, #dce2e9); border-radius: 8px; background: var(--bg-card, #fff); color: var(--text-primary, #263245); font-size: 12px; }
.native-workspace > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
button { flex-shrink: 0; border: 1px solid #8797ab; border-radius: 5px; background: transparent; padding: 4px 8px; color: inherit; cursor: pointer; }
[role=alert] { color: #b33434; }
</style>
