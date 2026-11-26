<template>
  <section class="resource-topology" aria-label="端边云资源分布">
    <header class="resource-topology__head">
      <div><span>DEPLOYMENT OVERVIEW</span><h2>设备与执行能力</h2></div>
      <p>按部署位置查看设备、执行能力和云端模型。</p>
    </header>
    <p v-if="nodesError" class="resource-topology__error" role="status">{{ nodesError }}</p>
    <div v-if="attentionItems.length" class="resource-topology__attention" role="status">
      <strong>需要关注</strong>
      <button v-for="item in attentionItems" :key="item.profile.resourceId" type="button" @click="emit('open', item)">
        {{ resourceDisplayName(item) }} · {{ ['device', 'local'].includes(item.profile.deploymentTier || '') ? '查看状态' : connectionGuidance(item.snapshot.healthStatus).action }}
      </button>
    </div>
    <div class="resource-topology__grid">
      <section v-for="group in groups" :key="group.id" class="resource-topology__column" :class="`is-${group.id}`">
        <header>
          <strong>{{ group.label }}</strong>
          <span v-if="group.id === 'cloud'">{{ modelGroups.length }} 个提供商 · {{ cloudModels.length + providerModels.length }} 个模型或服务</span>
          <span v-else>{{ group.devices.filter(device => device.nodeId).length }} 台设备</span>
        </header>
        <article v-for="device in group.devices" :key="device.key" class="resource-topology__device">
          <header class="resource-topology__device-head">
            <strong>{{ device.node?.profile.displayName || device.nodeId || '未关联设备' }}</strong>
            <small>{{ device.node ? nodeCapacity(device.node) : '设备信息未登记' }}</small>
            <button v-if="device.node" type="button" class="resource-topology__manage" :disabled="pendingNodes.includes(device.nodeId)" @click="emit('toggle-node', { nodeId: device.nodeId, enabled: !device.node.profile.enabled })">
              {{ pendingNodes.includes(device.nodeId) ? '保存中…' : device.node.profile.enabled ? '停用设备' : '启用设备' }}
            </button>
          </header>
          <section v-for="service in device.services" :key="service.profile.resourceId" class="resource-topology__service">
            <button type="button" class="resource-topology__card" @click="emit('open', service)">
              <span class="resource-topology__status" :class="`is-${service.snapshot.healthStatus}`"></span>
              <span class="resource-topology__identity"><strong>{{ resourceDisplayName(service) }}</strong><small>{{ customerResourceType(service.profile.runtimeKind || service.profile.resourceType) }} · {{ customerHealthLabel(service.snapshot.healthStatus) }}</small></span>
              <small>{{ resourceCapacityLabel(service) }}</small>
            </button>
            <div v-if="agentsFor(service).length" class="resource-topology__agents" aria-label="Agent 能力">
              <button v-for="agent in agentsFor(service)" :key="agent.profile.resourceId" type="button" class="resource-topology__agent" @click="emit('open', agent)">
                <strong>{{ resourceDisplayName(agent) }}</strong><small>{{ resourceCapacityLabel(agent) }}</small>
              </button>
            </div>
          </section>
          <div v-if="device.unassignedAgents.length" class="resource-topology__agents" aria-label="未关联执行服务的 Agent 能力">
            <small>宿主服务未登记</small>
            <button v-for="agent in device.unassignedAgents" :key="agent.profile.resourceId" type="button" class="resource-topology__agent" @click="emit('open', agent)"><strong>{{ resourceDisplayName(agent) }}</strong><small>{{ resourceCapacityLabel(agent) }}</small></button>
          </div>
          <p v-if="!device.services.length && !device.unassignedAgents.length">尚未登记执行服务</p>
        </article>
        <section v-if="group.id === 'cloud'" class="resource-topology__models" aria-label="云端模型">
          <p v-if="modelCatalogLoading" role="status">正在读取提供商档案和模型…</p>
          <p v-if="modelCatalogError" role="status">{{ modelCatalogError }}</p>
          <div v-for="group in modelGroups" :key="group.provider" class="resource-topology__provider">
            <h3>{{ providerNames[group.provider.toLowerCase()] || group.provider }}</h3>
            <button v-for="model in group.registered" :key="model.profile.resourceId" type="button" class="resource-topology__card" @click="emit('open', model)">
              <span class="resource-topology__status" :class="`is-${model.snapshot.healthStatus}`"></span>
              <span class="resource-topology__identity">
                <strong>{{ resourceDisplayName(model) }}</strong>
                <small>{{ model.profile.enabled ? '已登记为任务资源' : '任务资源已停用' }} · {{ customerHealthLabel(model.snapshot.healthStatus) }}</small>
              </span>
            </button>
            <div v-for="model in group.catalog" :key="providerModelKey(model.provider, model.model)" class="resource-topology__card resource-topology__catalog-model">
              <span class="resource-topology__status"></span>
              <span class="resource-topology__identity"><strong>{{ model.model }}</strong><small>{{ providerModelStatus(model) }}</small></span>
              <RouterLink v-if="model.profile && !model.profile.usable && !model.discovered" to="/settings?tab=model">打开模型设置</RouterLink>
            </div>
          </div>
          <p v-if="!modelGroups.length && !modelCatalogLoading && !modelCatalogError">暂无匹配的模型</p>
        </section>
        <p v-else-if="!group.devices.length">暂无已连接设备</p>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { NodeCatalogItem, RuntimeResourceItem } from '@/services/api/agentos'
import { connectionGuidance, customerResourceType, customerHealthLabel, deploymentGroup, resourceDisplayName, resourceCapacityLabel, providerModelKey, providerModelStatus, type ProviderModel } from './resourceCenterPresentation'

const props = withDefaults(defineProps<{ items: RuntimeResourceItem[]; contextItems?: RuntimeResourceItem[]; providerModels?: ProviderModel[]; modelCatalogError?: string; modelCatalogLoading?: boolean; nodes?: NodeCatalogItem[]; nodesError?: string; pendingNodes?: string[] }>(), { nodes: () => [], providerModels: () => [], pendingNodes: () => [] })
const emit = defineEmits<{
  (event: 'open', item: RuntimeResourceItem): void
  (event: 'toggle-node', payload: { nodeId: string; enabled: boolean }): void
}>()
const models = computed(() => props.items.filter(item => ['model_endpoint', 'model_server'].includes(item.profile.runtimeKind || '') || item.profile.resourceType === 'model'))
const cloudModels = computed(() => models.value.filter(item => deploymentGroup(item.profile.deploymentTier).id === 'cloud'))
const providerNames: Record<string, string> = { deepseek: 'DeepSeek', glm: '智谱 GLM', qwen: '通义千问' }
const modelGroups = computed(() => {
  const providerOf = (item: RuntimeResourceItem) => item.profile.provider || '提供方未登记'
  const names = [...new Set([...cloudModels.value.map(providerOf), ...props.providerModels.map(item => item.provider)].map(name => name.toLowerCase()))]
  return names.map(provider => ({
    provider,
    registered: cloudModels.value.filter(item => providerOf(item).toLowerCase() === provider),
    catalog: props.providerModels.filter(item => item.provider.toLowerCase() === provider)
  }))
})
const agents = computed(() => props.items.filter(item => item.profile.runtimeKind === 'agent_instance'))
const services = computed(() => {
  const visible = props.items.filter(item => !cloudModels.value.includes(item) && !agents.value.includes(item))
  // Keep the host as context when a search/filter matches only an Agent.
  const hosts = (props.contextItems || []).filter(item => agents.value.some(agent => agent.profile.hostRuntimeId === item.profile.resourceId))
  return [...new Map([...visible, ...hosts].map(item => [item.profile.resourceId, item])).values()]
})
const agentsFor = (service: RuntimeResourceItem) => agents.value.filter(agent => agent.profile.hostRuntimeId === service.profile.resourceId)
const groupDefinitions = [{ id: 'device', label: '我的设备' }, { id: 'edge', label: '边缘节点' }, { id: 'cloud', label: '云端服务' }, { id: 'other', label: '其他位置' }]
const groups = computed(() => groupDefinitions.map(group => {
  const items = [...services.value, ...agents.value].filter(item => deploymentGroup(item.profile.deploymentTier).id === group.id)
  const nodes = props.nodes.filter(node => deploymentGroup(node.profile.placement).id === group.id)
  const keys = new Set([...nodes.map(node => node.profile.nodeId), ...items.map(item => item.profile.nodeId || '')])
  return { ...group, devices: [...keys].map(nodeId => {
    const ownServices = services.value.filter(item => items.includes(item) && (item.profile.nodeId || '') === nodeId)
    return { key: nodeId || 'unassigned', nodeId, node: nodes.find(node => node.profile.nodeId === nodeId), services: ownServices,
      unassignedAgents: agents.value.filter(item => items.includes(item) && (item.profile.nodeId || '') === nodeId && !ownServices.some(service => service.profile.resourceId === item.profile.hostRuntimeId)) }
  }) }
}).filter(group => group.id !== 'other' || group.devices.length))
const attentionItems = computed(() => props.items.filter(item => ['offline', 'degraded', 'unknown'].includes(item.snapshot.healthStatus)).slice(0, 3))
const nodeCapacity = (node: NodeCatalogItem) => {
  const capacity = node.profile.computeCapacity
  if (!capacity) return '算力未登记'
  const parts = []
  if (capacity.cpuCores) parts.push(`${capacity.cpuCores} 核 CPU`)
  if (capacity.memoryMb) parts.push(`${Math.round(capacity.memoryMb / 1024)} GB 内存`)
  if (capacity.gpuType) parts.push(capacity.gpuType)
  return parts.join(' · ') || '算力未登记'
}
</script>

<style scoped>
.resource-topology { margin: 18px 0; padding: 18px; border: 1px solid var(--border-light); border-radius: var(--radius-card, 8px); background: var(--bg-card); }
.resource-topology__head { display: flex; align-items: end; justify-content: space-between; gap: 20px; }
.resource-topology__head span { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }.resource-topology__head h2 { margin: 4px 0 0; font-size: 15px; }.resource-topology__head p { max-width: 390px; margin: 0; color: var(--text-muted); font-size: 11px; line-height: 1.6; }
.resource-topology__attention { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 14px 0; padding: 9px 10px; border-left: 3px solid var(--warning); background: color-mix(in srgb, var(--warning) 8%, var(--bg-input)); font-size: 11px; }.resource-topology__attention button { border: 0; color: var(--primary-color); background: transparent; cursor: pointer; font: inherit; }
.resource-topology__error { color: var(--text-muted); font-size: 11px; }
.resource-topology__grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.resource-topology__column { min-width: 0; padding: 10px; border: 1px solid var(--border-light); border-radius: 6px; background: var(--bg-input); }.resource-topology__column > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; color: var(--text-secondary); font-size: 11px; }.resource-topology__column > header span { color: var(--text-muted); font: 11px var(--font-mono, monospace); }.resource-topology__column > p { margin: 14px 0 4px; color: var(--text-muted); font-size: 10px; }
.resource-topology__card { display: grid; grid-template-columns: 7px minmax(0, 1fr); gap: 8px; width: 100%; margin-top: 7px; padding: 9px; border: 1px solid var(--border-light); border-radius: 5px; color: inherit; background: var(--bg-card); cursor: pointer; text-align: left; }.resource-topology__card:hover { border-color: var(--primary-line); }.resource-topology__card > small { grid-column: 2; color: var(--text-muted); font-size: 10px; }.resource-topology__identity { display: grid; gap: 3px; min-width: 0; }.resource-topology__identity strong { overflow: hidden; color: var(--text-primary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.resource-topology__identity small { color: var(--text-secondary); font-size: 10px; }.resource-topology__status { width: 7px; height: 7px; margin-top: 3px; border-radius: 50%; background: var(--text-muted); }.resource-topology__status.is-online { background: var(--success); }.resource-topology__status.is-degraded { background: var(--warning); }.resource-topology__status.is-offline { background: var(--danger); }
.resource-topology__manage { grid-column: 2; justify-self: start; min-height: 28px; padding: 0 9px; border: 1px solid var(--border-light); border-radius: 4px; color: var(--text-secondary); background: var(--bg-card); cursor: pointer; font: inherit; font-size: 10px; }.resource-topology__manage:hover:not(:disabled) { border-color: var(--primary-line); color: var(--primary-color); }.resource-topology__manage:disabled { cursor: wait; opacity: .6; }
@media (max-width: 760px) { .resource-topology__head { align-items: start; flex-direction: column; gap: 8px; }.resource-topology__grid { grid-template-columns: 1fr; } }
.resource-topology__device { margin-top: 10px; }
.resource-topology__device-head { display: grid; gap: 6px; padding: 8px 0; font-size: 12px; }
.resource-topology__device-head small, .resource-topology__device > p { color: var(--text-muted); font-size: 10px; }
.resource-topology__device-head .resource-topology__manage { grid-column: auto; }
.resource-topology__agents { display: grid; gap: 6px; margin: 0 0 12px 15px; padding: 8px 0 0 10px; border-left: 1px solid var(--border-light); }
.resource-topology__agent { display: grid; gap: 5px; padding: 8px; border: 0; border-radius: 4px; text-align: left; color: var(--text-primary); background: var(--bg-card); cursor: pointer; font: inherit; font-size: 11px; }
.resource-topology__agent small { color: var(--text-muted); font-size: 10px; }
.resource-topology__models > p { color: var(--text-muted); font-size: 11px; }
.resource-topology__provider { margin-top: 12px; }
.resource-topology__provider h3 { margin: 0 0 6px; color: var(--text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.resource-topology__catalog-model { cursor: default; }
.resource-topology__catalog-model:hover { border-color: var(--border-light); }
.resource-topology__catalog-model a { grid-column: 2; color: var(--primary-color); font-size: 11px; }
</style>
