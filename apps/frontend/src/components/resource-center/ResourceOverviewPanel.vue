<template>
  <section class="resource-overview-panel" aria-label="系统资源">
    <div class="resource-summary" aria-label="资源摘要">
      <div class="resource-summary__intro">
        <span class="resource-summary__eyebrow">RESOURCE CATALOG</span>
        <strong>运行时资源目录</strong>
        <span>来自 ResourceService 的只读快照</span>
      </div>
      <div class="resource-summary__metrics">
        <div class="resource-summary__metric">
          <span>登记资源</span>
          <strong>{{ resources.length }}</strong>
          <small>profiles</small>
        </div>
        <div class="resource-summary__metric resource-summary__metric--health">
          <span>健康状态</span>
          <strong>{{ healthyResourceCount }}</strong>
          <small>online / {{ unknownResourceCount }} unknown</small>
        </div>
        <div class="resource-summary__metric resource-summary__metric--enabled">
          <span>已启用</span>
          <strong>{{ enabledResourceCount }}</strong>
          <small>可参与调度</small>
        </div>
      </div>
    </div>

    <div class="resource-toolbar" aria-label="资源筛选">
      <label class="resource-search" :class="{ 'has-query': searchText }">
        <span class="resource-search__icon" aria-hidden="true"><el-icon><Search /></el-icon></span>
        <span class="resource-search__copy">
          <span class="resource-search__label">筛选资源</span>
          <input v-model="searchText" type="search" placeholder="搜索 Resource ID 或 capability" />
        </span>
        <kbd>/</kbd>
      </label>
      <div class="resource-toolbar__meta">
        <span class="resource-toolbar__count"><b>{{ filteredResources.length }}</b> / {{ resources.length }} 个资源</span>
        <span class="resource-toolbar__mode"><i aria-hidden="true"></i> 只读</span>
      </div>
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
      <div class="resource-list__header" aria-hidden="true">
        <span>资源</span>
        <span>能力</span>
        <div class="resource-list__header-facts">
          <span>Health</span>
          <span>Slots</span>
          <span>Observed</span>
          <span>Enabled</span>
        </div>
      </div>
      <article v-for="item in filteredResources" :key="item.profile.resourceId" class="resource-row">
        <div class="resource-row__identity">
          <span class="resource-row__icon" aria-hidden="true">
            <el-icon><Cpu /></el-icon>
            <i :class="`resource-row__health-dot is-${item.snapshot.healthStatus}`"></i>
          </span>
          <div>
            <strong>{{ item.profile.resourceId }}</strong>
            <span>{{ item.profile.resourceType }} · v{{ item.profile.version }}</span>
          </div>
        </div>
        <div class="resource-row__capabilities">
          <span v-for="capability in item.profile.capabilities" :key="capability">{{ capability }}</span>
        </div>
        <dl class="resource-row__facts">
          <div><dt>Health</dt><dd :class="`is-${item.snapshot.healthStatus}`"><i class="resource-status-dot" aria-hidden="true"></i>{{ healthLabel(item.snapshot.healthStatus) }}</dd></div>
          <div><dt>Slots</dt><dd>{{ item.snapshot.availableSlots }} / {{ item.profile.capacity }}</dd></div>
          <div><dt>Observed</dt><dd>{{ formatDate(item.snapshot.observedAt) }}</dd></div>
          <div><dt>Enabled</dt><dd :class="item.profile.enabled ? 'is-enabled' : 'is-disabled'">{{ item.profile.enabled ? '已启用' : '已停用' }}</dd></div>
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

const healthyResourceCount = computed(() => resources.value.filter(item => item.snapshot.healthStatus === 'online').length)
const unknownResourceCount = computed(() => resources.value.filter(item => item.snapshot.healthStatus === 'unknown').length)
const enabledResourceCount = computed(() => resources.value.filter(item => item.profile.enabled).length)

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
.resource-overview-panel {
  --resource-surface: color-mix(in srgb, var(--bg-card) 92%, var(--bg-panel));
  --resource-inset: color-mix(in srgb, var(--bg-input) 78%, var(--bg-card));
  --resource-grid: minmax(220px, 1.1fr) minmax(180px, 1fr) minmax(310px, 1.3fr);
  min-width: 0;
  color: var(--text-primary);
}
.resource-summary {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 24px;
  margin: 20px 0 12px;
  padding: 16px 18px;
  border: 1px solid color-mix(in srgb, var(--primary-color) 15%, var(--border-light));
  border-radius: var(--radius-card, 9px);
  background: linear-gradient(105deg, color-mix(in srgb, var(--primary-color) 9%, var(--bg-card)), var(--resource-surface) 48%);
  box-shadow: var(--shadow-sm);
}
.resource-summary__intro { display: grid; align-content: center; gap: 3px; min-width: 190px; }
.resource-summary__intro strong { color: var(--text-primary); font-size: 14px; font-weight: 650; }
.resource-summary__intro > span:last-child { color: var(--text-muted); font-size: 10px; }
.resource-summary__eyebrow { color: var(--primary-color); font: 9px var(--font-mono, monospace); letter-spacing: .12em; }
.resource-summary__metrics { display: grid; grid-template-columns: repeat(3, minmax(110px, 1fr)); min-width: min(480px, 50%); }
.resource-summary__metric { display: grid; align-content: center; gap: 1px; padding: 0 18px; border-left: 1px solid var(--border-light); }
.resource-summary__metric span, .resource-summary__metric small { color: var(--text-muted); font-size: 10px; }
.resource-summary__metric strong { color: var(--text-primary); font: 650 20px/1.2 var(--font-mono, monospace); }
.resource-summary__metric small { color: var(--text-secondary); font: 9px var(--font-mono, monospace); white-space: nowrap; }
.resource-summary__metric--health strong { color: var(--success); }
.resource-summary__metric--enabled strong { color: var(--primary-color); }
.resource-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 0 12px; color: var(--text-muted); font-size: 11px; }
.resource-search { display: flex; align-items: center; gap: 9px; width: min(500px, 100%); min-height: 42px; padding: 0 11px; border: 1px solid var(--border-light); border-radius: var(--radius-control, 6px); color: var(--text-muted); background: var(--resource-inset); transition: var(--transition); }
.resource-search:hover, .resource-search:focus-within, .resource-search.has-query { border-color: var(--primary-line); background: var(--bg-input); }
.resource-search__icon { display: inline-grid; place-items: center; color: var(--primary-color); }
.resource-search__copy { display: grid; min-width: 0; flex: 1; gap: 0; }
.resource-search__label { color: var(--text-muted); font-size: 9px; line-height: 1.1; }
.resource-search input { width: 100%; min-width: 0; border: 0; outline: 0; color: var(--text-primary); background: transparent; font: 11px/1.4 var(--font-sans); }
.resource-search input::placeholder { color: var(--text-secondary); }
.resource-search kbd { min-width: 18px; padding: 2px 5px; border: 1px solid var(--border-light); border-radius: 4px; color: var(--text-muted); background: var(--bg-card); font: 10px var(--font-mono, monospace); text-align: center; }
.resource-toolbar__meta { display: flex; align-items: center; gap: 14px; white-space: nowrap; }
.resource-toolbar__count b { color: var(--text-primary); font: 650 12px var(--font-mono, monospace); }
.resource-toolbar__mode { display: inline-flex; align-items: center; gap: 5px; color: var(--text-muted); font: 9px var(--font-mono, monospace); text-transform: uppercase; letter-spacing: .05em; }
.resource-toolbar__mode i { width: 5px; height: 5px; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 3px var(--success-fade); }
.resource-list { overflow: hidden; border: 1px solid var(--border-light); border-radius: var(--radius-card, 9px); background: var(--resource-surface); box-shadow: var(--shadow-sm); }
.resource-list__header { display: grid; grid-template-columns: var(--resource-grid); align-items: center; gap: 24px; min-height: 34px; padding: 0 16px; border-bottom: 1px solid var(--border-light); color: var(--text-muted); background: var(--resource-inset); font: 9px var(--font-mono, monospace); letter-spacing: .04em; text-transform: uppercase; }
.resource-list__header-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.resource-row { display: grid; grid-template-columns: var(--resource-grid); align-items: center; gap: 24px; min-height: 88px; padding: 15px 16px; border-bottom: 1px solid var(--border-light); background: var(--resource-surface); transition: var(--transition); }
.resource-row:last-child { border-bottom: 0; }
.resource-row:hover { background: var(--surface-hover); box-shadow: inset 2px 0 0 var(--primary-color); }
.resource-row__identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.resource-row__icon { position: relative; display: inline-grid; place-items: center; flex: 0 0 auto; width: 36px; height: 36px; border: 1px solid var(--primary-line); border-radius: var(--radius-control, 6px); color: var(--primary-color); background: var(--primary-fade); }
.resource-row__health-dot { position: absolute; right: -3px; bottom: -3px; width: 8px; height: 8px; border: 2px solid var(--resource-surface); border-radius: 50%; background: var(--warning); }
.resource-row__health-dot.is-online { background: var(--success); }
.resource-row__health-dot.is-degraded { background: var(--warning); }
.resource-row__health-dot.is-offline { background: var(--danger); }
.resource-row__identity div { min-width: 0; }
.resource-row__identity strong, .resource-row__identity span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-row__identity strong { color: var(--text-primary); font: 600 11px var(--font-mono, monospace); }
.resource-row__identity span { margin-top: 4px; color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.resource-row__capabilities { display: flex; gap: 5px; min-width: 0; flex-wrap: wrap; }
.resource-row__capabilities span { padding: 4px 7px; border: 1px solid color-mix(in srgb, var(--border-light) 82%, var(--primary-color)); border-radius: 4px; color: var(--text-secondary); background: color-mix(in srgb, var(--bg-input) 76%, transparent); font: 10px var(--font-mono, monospace); }
.resource-row__facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0; }
.resource-row__facts div { min-width: 0; }
.resource-row__facts dt { display: none; color: var(--text-muted); font-size: 10px; }
.resource-row__facts dd { display: flex; align-items: center; gap: 5px; margin: 0; overflow: hidden; color: var(--text-secondary); font: 11px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.resource-row__facts dd.is-unknown { color: var(--warning); }
.resource-row__facts dd.is-online { color: var(--success); }
.resource-row__facts dd.is-degraded { color: var(--warning); }
.resource-row__facts dd.is-offline, .resource-row__facts dd.is-disabled { color: var(--danger); }
.resource-row__facts dd.is-enabled { color: var(--text-secondary); }
.resource-status-dot { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: currentColor; }
.resource-state { display: grid; place-items: center; align-content: center; gap: 8px; min-height: 280px; color: var(--text-secondary); font-size: 12px; text-align: center; }
.resource-state strong { color: var(--text-primary); font-size: 14px; }
.resource-state span { line-height: 1.6; }
.resource-state--error { color: var(--danger, #b64d55); }
.resource-state button { min-height: 32px; padding: 0 12px; border: 1px solid var(--primary-line); border-radius: 5px; color: var(--primary-color); background: var(--primary-fade); cursor: pointer; font: inherit; font-size: 11px; }
@media (max-width: 900px) {
  .resource-summary { flex-direction: column; gap: 16px; }
  .resource-summary__metrics { min-width: 0; }
  .resource-list__header { display: none; }
  .resource-row { grid-template-columns: 1fr; gap: 12px; min-height: 0; padding: 16px; }
  .resource-row__facts { gap: 10px; }
  .resource-row__facts dt { display: block; }
  .resource-row__facts dd { margin-top: 3px; }
}
@media (max-width: 560px) {
  .resource-summary { margin-top: 14px; padding: 14px; }
  .resource-summary__metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .resource-summary__metric { padding: 0 9px; }
  .resource-summary__metric strong { font-size: 17px; }
  .resource-summary__metric small { overflow: hidden; text-overflow: ellipsis; }
  .resource-toolbar { align-items: stretch; flex-direction: column; gap: 9px; }
  .resource-toolbar__meta { justify-content: space-between; }
  .resource-row__facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
