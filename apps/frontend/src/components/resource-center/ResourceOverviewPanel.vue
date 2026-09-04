<template>
  <section class="resource-overview-panel" aria-label="系统资源">
    <div class="resource-toolbar" aria-label="资源筛选">
      <label class="resource-search">
        <el-icon aria-hidden="true"><Search /></el-icon>
        <input v-model="searchText" type="search" placeholder="搜索 Resource ID 或 capability" />
      </label>
      <span>{{ filteredResources.length }} / {{ resources.length }} 个资源</span>
    </div>

    <section v-if="loading && !resources.length" class="resource-state" role="status">
      <strong>正在读取 ResourceService</strong>
      <span>只读加载系统 Resource profile…</span>
    </section>
    <section v-else-if="errorMessage" class="resource-state resource-state--error" role="alert">
      <strong>资源中心暂时不可用</strong>
      <span>{{ errorMessage }}</span>
      <button type="button" @click="loadResources">重新加载</button>
    </section>
    <section v-else-if="!filteredResources.length" class="resource-state" role="status">
      <strong>{{ searchText ? '没有匹配的 Resource' : '暂无已登记 Resource' }}</strong>
      <span>{{ searchText ? '换一个 ID 或 capability 试试。' : 'ResourceService 当前没有可展示的 profile。' }}</span>
    </section>
    <section v-else class="resource-list" aria-label="System Resources">
      <article v-for="item in filteredResources" :key="item.profile.resourceId" class="resource-row">
        <div class="resource-row__identity">
          <span class="resource-row__icon" aria-hidden="true"><el-icon><Cpu /></el-icon></span>
          <div>
            <strong>{{ item.profile.resourceId }}</strong>
            <span>{{ item.profile.resourceType }} · v{{ item.profile.version }}</span>
          </div>
        </div>
        <div class="resource-row__capabilities">
          <span v-for="capability in item.profile.capabilities" :key="capability">{{ capability }}</span>
        </div>
        <dl class="resource-row__facts">
          <div><dt>Health</dt><dd :class="`is-${item.snapshot.healthStatus}`">{{ healthLabel(item.snapshot.healthStatus) }}</dd></div>
          <div><dt>Slots</dt><dd>{{ item.snapshot.availableSlots }} / {{ item.profile.capacity }}</dd></div>
          <div><dt>Observed</dt><dd>{{ formatDate(item.snapshot.observedAt) }}</dd></div>
          <div><dt>Enabled</dt><dd>{{ item.profile.enabled ? '已启用' : '已停用' }}</dd></div>
        </dl>
      </article>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Cpu, Search } from '@element-plus/icons-vue'
import { agentosApi, type RuntimeResourceHealth, type RuntimeResourceItem } from '@/services/api/agentos'

const resources = ref<RuntimeResourceItem[]>([])
const searchText = ref('')
const loading = ref(false)
const errorMessage = ref('')
let controller: AbortController | null = null

const filteredResources = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase()
  if (!query) return resources.value
  return resources.value.filter(item => [
    item.profile.resourceId,
    item.profile.resourceType,
    ...item.profile.capabilities
  ].some(value => value.toLocaleLowerCase().includes(query)))
})

const healthLabel = (value: RuntimeResourceHealth) => ({
  unknown: 'Unknown / 未知',
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Offline'
}[value] || `${value} / 未知`)

const formatDate = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '未观测'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

const loadResources = async () => {
  controller?.abort()
  controller = new AbortController()
  const requestController = controller
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await agentosApi.listResources({ signal: requestController.signal })
    if (requestController.signal.aborted || controller !== requestController) return
    resources.value = response.items
  } catch (error: unknown) {
    if ((error as { name?: string })?.name === 'CanceledError' || (error as { name?: string })?.name === 'AbortError') return
    errorMessage.value = '无法读取 ResourceService 的真实数据。'
  } finally {
    if (controller === requestController && !requestController.signal.aborted) loading.value = false
  }
}

defineExpose({ loadResources })

onMounted(() => { void loadResources() })
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.resource-overview-panel { min-width: 0; color: var(--text-primary); }
.resource-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 0; color: var(--text-muted); font-size: 11px; }
.resource-search { display: flex; align-items: center; gap: 8px; width: min(480px, 100%); min-height: 34px; padding: 0 10px; border-bottom: 1px solid var(--border-light); color: var(--text-muted); }
.resource-search input { width: 100%; border: 0; outline: 0; color: var(--text-primary); background: transparent; font: inherit; }
.resource-list { border-top: 1px solid var(--border-light); }
.resource-row { display: grid; grid-template-columns: minmax(220px, 1.1fr) minmax(180px, 1fr) minmax(310px, 1.3fr); align-items: center; gap: 24px; padding: 18px 16px; border-bottom: 1px solid var(--border-light); background: var(--bg-card); }
.resource-row:hover { background: var(--bg-input); }
.resource-row__identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.resource-row__icon { display: inline-grid; place-items: center; width: 30px; height: 30px; border: 1px solid var(--primary-line); border-radius: 5px; color: var(--primary-color); background: var(--primary-fade); }
.resource-row__identity div { min-width: 0; }
.resource-row__identity strong, .resource-row__identity span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-row__identity strong { font: 11px var(--font-mono, monospace); }
.resource-row__identity span { margin-top: 4px; color: var(--text-muted); font-size: 10px; }
.resource-row__capabilities { display: flex; gap: 5px; min-width: 0; flex-wrap: wrap; }
.resource-row__capabilities span { padding: 3px 6px; border: 1px solid var(--border-light); color: var(--text-secondary); font: 10px var(--font-mono, monospace); }
.resource-row__facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0; }
.resource-row__facts div { min-width: 0; }
.resource-row__facts dt { color: var(--text-muted); font-size: 10px; }
.resource-row__facts dd { margin: 4px 0 0; overflow: hidden; color: var(--text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.resource-row__facts dd.is-unknown { color: var(--warning, #a36a16); }
.resource-state { display: grid; place-items: center; align-content: center; gap: 8px; min-height: 280px; color: var(--text-secondary); font-size: 12px; text-align: center; }
.resource-state strong { color: var(--text-primary); font-size: 14px; }
.resource-state span { line-height: 1.6; }
.resource-state--error { color: var(--danger, #b64d55); }
.resource-state button { min-height: 32px; padding: 0 12px; border: 1px solid var(--primary-line); border-radius: 5px; color: var(--primary-color); background: var(--primary-fade); cursor: pointer; font: inherit; font-size: 11px; }
@media (max-width: 900px) {
  .resource-row { grid-template-columns: 1fr; gap: 12px; }
}
</style>
