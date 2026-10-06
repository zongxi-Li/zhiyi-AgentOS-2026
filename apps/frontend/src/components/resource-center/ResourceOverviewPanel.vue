<template>
  <section class="resource-overview-panel" aria-label="系统资源">
    <div class="resource-summary" aria-label="资源摘要">
      <div class="resource-summary__intro">
        <span class="resource-summary__eyebrow">RESOURCE CATALOG</span>
        <strong>运行时资源目录</strong>
        <span>来自 ResourceService 的只读快照</span>
      </div>
      <div class="resource-summary__metrics">
        <div v-for="tier in tierStats" :key="tier.id" class="resource-summary__metric resource-summary__metric--tier" :class="`is-tier-${tier.id}`">
          <span>{{ tier.label }}</span>
          <strong>{{ tier.count }}</strong>
          <small>资源</small>
        </div>
        <div class="resource-summary__metric resource-summary__metric--compute">
          <span>总算力</span>
          <strong>{{ computeTotals.hasCapacity ? `${computeTotals.cpu}核` : '未观测' }}</strong>
          <small v-if="computeTotals.hasCapacity">{{ computeTotals.memory }}G 内存<template v-if="computeTotals.gpu > 0"> · {{ computeTotals.gpu }}G GPU</template></small>
          <small v-else>未登记算力</small>
        </div>
        <div class="resource-summary__metric resource-summary__metric--health">
          <span>健康分布</span>
          <strong>{{ healthyResourceCount }}</strong>
          <small>在线 · {{ degradedResourceCount }} 降级 · {{ offlineResourceCount }} 离线</small>
        </div>
      </div>
    </div>

    <div class="resource-toolbar" aria-label="资源筛选">
      <label class="resource-search" :class="{ 'has-query': searchText }">
        <span class="resource-search__icon" aria-hidden="true"><el-icon><Search /></el-icon></span>
        <span class="resource-search__copy">
          <span class="resource-search__label">筛选资源</span>
          <input ref="searchInput" v-model="searchText" type="search" placeholder="搜索 Resource ID 或 capability" />
        </span>
        <kbd>/</kbd>
      </label>
      <div class="resource-toolbar__meta">
        <span class="resource-toolbar__count"><b>{{ filteredResources.length }}</b> / {{ resources.length }} 个资源</span>
        <span class="resource-toolbar__mode"><i aria-hidden="true"></i> 只读</span>
      </div>
    </div>

    <div v-if="domainOptions.length" class="resource-domain-filter" role="group" aria-label="按领域筛选">
      <button type="button" :class="{ active: !selectedDomain }" @click="selectedDomain = ''">全部</button>
      <button
        v-for="domain in domainOptions"
        :key="domain.name"
        type="button"
        :class="{ active: selectedDomain === domain.name }"
        @click="selectedDomain = selectedDomain === domain.name ? '' : domain.name"
      >{{ domain.name }}<small>{{ domain.count }}</small></button>
    </div>

    <section v-if="loading && !resources.length" class="resource-state" role="status">
      <BrandLoader title="正在读取 ResourceService" subtitle="只读加载系统 Resource profile…" />
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
    <div v-else class="resource-groups" aria-label="系统资源">
      <section v-for="group in groupedResources" :key="group.tier" class="resource-tier-group" :class="`is-tier-${group.tier}`">
        <header class="resource-tier-group__header">
          <span class="resource-tier-group__dot" aria-hidden="true"></span>
          <strong>{{ group.label }}</strong>
          <span class="resource-tier-group__count">{{ group.items.length }} 个资源</span>
        </header>
        <div class="resource-list">
          <article v-for="item in group.items" :key="item.profile.resourceId" class="resource-row" @click="openDetail(item)">
            <div class="resource-row__identity">
              <span class="resource-row__icon" aria-hidden="true" :style="{ '--tile-tone': resourceTypeMeta(item.profile.resourceType).tone }">
                <el-icon><component :is="resourceTypeIcon(item.profile.resourceType)" /></el-icon>
                <i :class="`resource-row__health-dot is-${item.snapshot.healthStatus}`"></i>
              </span>
              <div>
                <strong>{{ item.profile.resourceId }}</strong>
                <span class="resource-row__meta"><ResourceTypeBadge :type="item.profile.resourceType" /> · v{{ item.profile.version }}</span>
              </div>
            </div>
            <div class="resource-row__capabilities">
              <span v-for="capability in item.profile.capabilities" :key="capability">{{ capability }}</span>
            </div>
            <dl class="resource-row__facts">
              <div><dt>Health</dt><dd :class="`is-${item.snapshot.healthStatus}`"><i class="resource-status-dot" aria-hidden="true"></i>{{ healthLabel(item.snapshot.healthStatus) }}</dd></div>
              <div><dt>算力</dt><dd class="resource-row__capacity">{{ formatCapacity(item.profile.computeCapacity) }}</dd></div>
              <div><dt>利用率</dt><dd class="resource-row__util"><span class="resource-row__util-track"><i :style="{ width: utilizationPercent(item.snapshot.utilization) }"></i></span><em>{{ formatPercent(item.snapshot.utilization) }}</em></dd></div>
              <div><dt>延迟</dt><dd>{{ formatMetric(item.snapshot.latencyMs, 'ms') }}</dd></div>
            </dl>
            <div class="resource-row__extra">
              <span class="resource-row__privacy">{{ item.profile.privacyLevel || 'internal' }}</span>
              <span v-if="item.profile.dataZone" class="resource-row__zone">{{ item.profile.dataZone }}</span>
              <button type="button" class="resource-row__open" :aria-label="`查看 ${item.profile.resourceId} 详情`" @click.stop="openDetail(item)">详情</button>
            </div>
          </article>
        </div>
      </section>
    </div>
  </section>

  <el-drawer v-model="drawerOpen" :title="selectedResource ? selectedResource.profile.resourceId : '资源详情'" size="440px" append-to-body class="resource-detail-drawer">
    <ResourceDetailPanel v-if="selectedResource" :item="selectedResource" @enabled-changed="handleEnabledChanged" />
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { agentosApi, type RuntimeResourceItem } from '@/services/api/agentos'
import ResourceDetailPanel from './ResourceDetailPanel.vue'
import ResourceTypeBadge from './ResourceTypeBadge.vue'
import { formatCapacity, formatMetric, formatPercent, healthLabel, resourceTypeMeta } from '@/utils/resourceFormat'
import { resourceTypeIcon } from '@/utils/resourceTypeIcons'

const resources = ref<RuntimeResourceItem[]>([])
const searchText = ref('')
const selectedDomain = ref('')
const loading = ref(false)
const errorMessage = ref('')
const selectedResource = ref<RuntimeResourceItem | null>(null)
const drawerOpen = ref(false)
const searchInput = ref<HTMLInputElement | null>(null)
let controller: AbortController | null = null

const TIER_ORDER: Array<{ id: string; label: string }> = [
  { id: 'local', label: '本地' },
  { id: 'terminal', label: '端侧' },
  { id: 'edge', label: '边缘' },
  { id: 'cloud', label: '云端' }
]

const healthyResourceCount = computed(() => resources.value.filter(item => item.snapshot.healthStatus === 'online').length)
const degradedResourceCount = computed(() => resources.value.filter(item => item.snapshot.healthStatus === 'degraded').length)
const offlineResourceCount = computed(() => resources.value.filter(item => item.snapshot.healthStatus === 'offline').length)

const tierStats = computed(() => TIER_ORDER.map(tier => ({
  ...tier,
  count: resources.value.filter(item => (item.profile.deploymentTier || 'local') === tier.id).length
})))

const computeTotals = computed(() => {
  let cpu = 0
  let memory = 0
  let gpu = 0
  let hasCapacity = false
  for (const item of resources.value) {
    const capacity = item.profile.computeCapacity
    if (!capacity) continue
    hasCapacity = true
    cpu += capacity.cpuCores
    memory += Math.round(capacity.memoryMb / 1024)
    gpu += Math.round(capacity.gpuMemoryMb / 1024)
  }
  return { cpu, memory, gpu, hasCapacity }
})

const domainOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const item of resources.value) {
    for (const domain of item.profile.domains || []) {
      counts.set(domain, (counts.get(domain) || 0) + 1)
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name, count]) => ({ name, count }))
})

const filteredResources = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase()
  const domain = selectedDomain.value
  return resources.value.filter(item => {
    if (domain && !(item.profile.domains || []).includes(domain)) return false
    if (!query) return true
    return [
      item.profile.resourceId,
      item.profile.resourceType,
      ...item.profile.capabilities,
      item.profile.deploymentTier || ''
    ].some(value => (value || '').toLocaleLowerCase().includes(query))
  })
})

const filteredCount = computed(() => filteredResources.value.length)

const groupedResources = computed(() => {
  const groups = new Map<string, RuntimeResourceItem[]>()
  for (const item of filteredResources.value) {
    const tier = item.profile.deploymentTier || 'local'
    if (!groups.has(tier)) groups.set(tier, [])
    groups.get(tier)!.push(item)
  }
  return TIER_ORDER
    .filter(tier => groups.has(tier.id))
    .map(tier => ({ tier: tier.id, label: tier.label, items: groups.get(tier.id)! }))
})

const utilizationPercent = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

const openDetail = (item: RuntimeResourceItem) => {
  selectedResource.value = item
  drawerOpen.value = true
}

const handleEnabledChanged = (payload: { resourceId: string; enabled: boolean }) => {
  for (const item of resources.value) {
    if (item.profile.resourceId === payload.resourceId) {
      item.profile.enabled = payload.enabled
    }
  }
  if (selectedResource.value?.profile.resourceId === payload.resourceId) {
    selectedResource.value = {
      ...selectedResource.value,
      profile: { ...selectedResource.value.profile, enabled: payload.enabled }
    }
  }
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

const focusSearch = (event: KeyboardEvent) => {
  if (event.key !== '/') return
  const target = event.target as HTMLElement | null
  const tag = target?.tagName?.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return
  event.preventDefault()
  searchInput.value?.focus()
}

onMounted(() => { void loadResources(); window.addEventListener('keydown', focusSearch) })
onBeforeUnmount(() => { controller?.abort(); window.removeEventListener('keydown', focusSearch) })
</script>

<style scoped>
.resource-overview-panel {
  --resource-surface: color-mix(in srgb, var(--bg-card) 92%, var(--bg-panel));
  --resource-inset: color-mix(in srgb, var(--bg-input) 78%, var(--bg-card));
  --resource-grid: minmax(180px, 0.9fr) minmax(140px, 0.7fr) minmax(360px, 1.6fr) auto;
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
.resource-summary__metrics { display: grid; grid-template-columns: repeat(6, minmax(96px, 1fr)); min-width: min(600px, 62%); }
.resource-summary__metric { display: grid; align-content: center; gap: 1px; padding: 0 18px; border-left: 1px solid var(--border-light); }
.resource-summary__metric span, .resource-summary__metric small { color: var(--text-muted); font-size: 10px; }
.resource-summary__metric strong { color: var(--text-primary); font: 650 20px/1.2 var(--font-mono, monospace); }
.resource-summary__metric small { color: var(--text-secondary); font: 9px var(--font-mono, monospace); white-space: nowrap; }
.resource-summary__metric--health strong { color: var(--success); }
.resource-summary__metric--compute strong { color: var(--primary-color); }
.resource-summary__metric--tier strong { color: var(--text-secondary); }
.resource-summary__metric--tier.is-tier-cloud strong { color: var(--primary-color); }
.resource-summary__metric--tier.is-tier-edge strong { color: var(--success); }
.resource-summary__metric--tier.is-tier-terminal strong { color: var(--accent-color, #6f668f); }
.resource-summary__metric--tier.is-tier-local strong { color: var(--text-secondary); }
.resource-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 0 12px; color: var(--text-muted); font-size: 11px; }
.resource-domain-filter { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 0 12px; }
.resource-domain-filter button { display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border: 1px solid var(--border-light); border-radius: 999px; color: var(--text-secondary); background: var(--bg-input); cursor: pointer; font: inherit; font-size: 10px; transition: var(--transition); }
.resource-domain-filter button:hover { border-color: var(--primary-line); color: var(--primary-color); }
.resource-domain-filter button.active { border-color: color-mix(in srgb, var(--primary-color) 62%, transparent); color: var(--primary-color); background: var(--primary-fade); }
.resource-domain-filter button small { color: var(--text-muted); font-size: 9px; }
.resource-domain-filter button.active small { color: var(--primary-color); }
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
.resource-groups { display: grid; gap: 16px; }
.resource-tier-group { display: grid; gap: 8px; }
.resource-tier-group__header { display: flex; align-items: center; gap: 8px; padding: 2px 2px 6px; color: var(--text-secondary); }
.resource-tier-group__header strong { font-size: 12px; font-weight: 650; }
.resource-tier-group__count { margin-left: auto; color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.resource-tier-group__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary-color); }
.is-tier-local .resource-tier-group__dot { background: var(--text-secondary); }
.is-tier-terminal .resource-tier-group__dot { background: var(--accent-color, #6f668f); }
.is-tier-edge .resource-tier-group__dot { background: var(--success); }
.is-tier-cloud .resource-tier-group__dot { background: var(--primary-color); }
.resource-list { overflow: hidden; border: 1px solid var(--border-light); border-radius: var(--radius-card, 9px); background: var(--resource-surface); box-shadow: var(--shadow-sm); }
.resource-row { display: grid; grid-template-columns: var(--resource-grid); align-items: center; gap: 24px; min-height: 88px; padding: 15px 16px; border-bottom: 1px solid var(--border-light); background: var(--resource-surface); transition: var(--transition); cursor: pointer; }
.resource-row:last-child { border-bottom: 0; }
.resource-row:hover { background: var(--surface-hover); box-shadow: inset 2px 0 0 var(--primary-color); }
.resource-row__identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.resource-row__icon { position: relative; display: inline-grid; place-items: center; flex: 0 0 auto; width: 36px; height: 36px; border-radius: 10px; color: color-mix(in srgb, var(--tile-tone, var(--primary-color)) 40%, #e9f5ff); background: linear-gradient(145deg, color-mix(in srgb, var(--tile-tone, var(--primary-color)) 34%, transparent), color-mix(in srgb, var(--tile-tone, var(--primary-color)) 10%, transparent) 55%, color-mix(in srgb, var(--tile-tone, var(--primary-color)) 24%, transparent)), var(--bg-input); border: 1px solid color-mix(in srgb, var(--tile-tone, var(--primary-color)) 46%, transparent); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.09), 0 0 12px color-mix(in srgb, var(--tile-tone, var(--primary-color)) 16%, transparent); transition: box-shadow var(--transition), border-color var(--transition); }
.resource-row__icon .el-icon { font-size: 18px; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.35)); }
.resource-row:hover .resource-row__icon { border-color: color-mix(in srgb, var(--tile-tone, var(--primary-color)) 70%, transparent); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12), 0 0 18px color-mix(in srgb, var(--tile-tone, var(--primary-color)) 30%, transparent); }
.resource-row__health-dot { position: absolute; right: -3px; bottom: -3px; width: 8px; height: 8px; border: 2px solid var(--resource-surface); border-radius: 50%; background: var(--warning); }
.resource-row__health-dot.is-online { background: var(--success); }
.resource-row__health-dot.is-degraded { background: var(--warning); }
.resource-row__health-dot.is-offline { background: var(--danger); }
.resource-row__identity div { min-width: 0; }
.resource-row__identity strong, .resource-row__identity span:not(.resource-row__icon) { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-row__identity strong { color: var(--text-primary); font: 600 11px var(--font-mono, monospace); }
.resource-row__identity span:not(.resource-row__icon) { margin-top: 4px; color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.resource-row__identity .resource-row__meta { display: inline-flex; align-items: center; gap: 5px; }
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
.resource-row__capacity { font-size: 9px !important; }
.resource-row__util { display: flex; align-items: center; gap: 6px; }
.resource-row__util-track { position: relative; display: inline-block; flex: 0 0 auto; width: 46px; height: 4px; border-radius: 2px; background: var(--border-light); overflow: hidden; }
.resource-row__util-track i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px; background: var(--primary-color); }
.resource-row__util em { font-style: normal; }
.resource-row__extra { display: flex; align-items: center; gap: 6px; justify-content: flex-end; }
.resource-row__privacy { padding: 2px 7px; border: 1px solid var(--border-light); border-radius: 999px; color: var(--text-muted); font: 9px var(--font-mono, monospace); white-space: nowrap; }
.resource-row__zone { color: var(--text-muted); font: 9px var(--font-mono, monospace); white-space: nowrap; }
.resource-row__open { min-height: 26px; padding: 0 10px; border: 1px solid var(--primary-line); border-radius: 5px; color: var(--primary-color); background: transparent; cursor: pointer; font-size: 10px; }
.resource-row__open:hover { background: var(--primary-fade); }
.resource-state { display: grid; place-items: center; align-content: center; gap: 8px; min-height: 280px; color: var(--text-secondary); font-size: 12px; text-align: center; }
.resource-state strong { color: var(--text-primary); font-size: 14px; }
.resource-state span { line-height: 1.6; }
.resource-state--error { color: var(--danger, #b64d55); }
.resource-state button { min-height: 32px; padding: 0 12px; border: 1px solid var(--primary-line); border-radius: 5px; color: var(--primary-color); background: var(--primary-fade); cursor: pointer; font: inherit; font-size: 11px; }
@media (max-width: 900px) {
  .resource-summary { flex-direction: column; gap: 16px; }
  .resource-summary__metrics { min-width: 0; }
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
