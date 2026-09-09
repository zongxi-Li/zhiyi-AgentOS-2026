<template>
  <div class="sidebar-view-stack">
    <InspectorSection v-if="selectedBinding" title="节点资源" :badge="healthLabel(selectedHealth)">
      <InspectorPropertyList :rows="[
        { label: 'resourceId', value: selectedBinding.resourceId, code: true },
        { label: 'deploymentTier', value: tierLabel(selectedBinding.deploymentTier) },
        { label: 'agentId', value: selectedBinding.agentId, code: true },
        { label: 'modelId', value: selectedBinding.modelId, code: true },
        { label: 'ExecutionBinding', value: selectedBinding.bindingId, code: true },
        { label: 'Attempt', value: selectedBinding.attemptId, code: true },
        { label: 'health', value: healthLabel(selectedHealth) }
      ]" />
    </InspectorSection>

    <InspectorSection v-else title="运行资源" :badge="resourceObservation ? 'observed' : 'not observed'">
      <div class="sidebar-metrics" aria-label="资源绑定统计">
        <div><strong>{{ boundResourceCount }}</strong><span>资源</span></div>
        <div><strong>{{ agentCount }}</strong><span>Agents</span></div>
        <div><strong>{{ modelCount }}</strong><span>Models</span></div>
      </div>
      <InspectorPropertyList :rows="[
        { label: 'bound attempts', value: resourceObservation?.bindings.length ?? '未观测' },
        { label: 'calls', value: '未观测' },
        { label: 'tokens', value: '未观测' },
        { label: 'source', value: resourceObservation?.source || '未观测' }
      ]" />
      <div v-if="boundResources.length" class="resource-list">
        <div v-for="resource in boundResources" :key="resource.resourceId" class="resource-list__row">
          <div>
            <strong>{{ resource.resourceId }}</strong>
            <span>{{ tierLabel(resource.deploymentTier) }} · {{ resource.agentId }} · {{ resource.modelId }}</span>
          </div>
          <span>{{ healthLabel(resource.health) }}</span>
        </div>
      </div>
      <div v-if="resourceObservation?.failoverEvents?.length" class="resource-switch-list" aria-label="资源切换记录">
        <strong>资源切换</strong>
        <span v-for="event in resourceObservation.failoverEvents" :key="event.eventId">
          {{ event.failedResources.map(item => item.resourceId).join('、') }} → {{ event.retryStepIds.join('、') || '原步骤' }}
        </span>
      </div>
      <p v-else class="sidebar-empty">{{ resourceObservation ? '当前 Run 没有可证明的资源绑定。' : '未观测到 Resource。' }}</p>
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ResourceBindingObservation, ResourceObservation } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import type { WorkbenchInspectorContext } from '@/workbench/types'
import { healthLabel, tierLabel } from '@/utils/resourceFormat'

const props = defineProps<{
  context: WorkbenchInspectorContext
  resourceObservation: ResourceObservation | null
}>()

const selectedBinding = computed<ResourceBindingObservation | null>(() => {
  const observation = props.resourceObservation
  const node = props.context.graphNode
  if (!observation || !node) return null
  return observation.bindings.find(item => (
    (node.attemptId && item.attemptId === node.attemptId)
    || (item.acgNodeId === node.acgNodeId && item.semanticTaskKey === node.semanticTaskKey)
  )) || null
})

const selectedHealth = computed(() => {
  const resourceId = selectedBinding.value?.resourceId
  return props.resourceObservation?.items.find(item => item.profile.resourceId === resourceId)?.snapshot.healthStatus || 'unknown'
})

const boundResources = computed(() => {
  const observation = props.resourceObservation
  if (!observation) return []
  const grouped = new Map<string, { resourceId: string; agentId: string; modelId: string; health: string; deploymentTier: string | null }>()
  for (const binding of observation.bindings) {
    if (grouped.has(binding.resourceId)) continue
    const profile = observation.items.find(item => item.profile.resourceId === binding.resourceId)
    grouped.set(binding.resourceId, {
      resourceId: binding.resourceId,
      agentId: binding.agentId,
      modelId: binding.modelId,
      health: profile?.snapshot.healthStatus || 'unknown',
      deploymentTier: binding.deploymentTier || profile?.profile.deploymentTier || null
    })
  }
  return [...grouped.values()]
})

const boundResourceCount = computed(() => boundResources.value.length)
const agentCount = computed(() => new Set((props.resourceObservation?.bindings || []).map(item => item.agentId)).size)
const modelCount = computed(() => new Set((props.resourceObservation?.bindings || []).map(item => item.modelId)).size)
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.sidebar-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 8px; }
.sidebar-metrics > div { display: grid; gap: 2px; min-width: 0; }
.sidebar-metrics strong { color: var(--wb-text); font: 16px var(--font-mono, monospace); }
.sidebar-metrics span { color: var(--wb-text-muted); font-size: 10px; }
.resource-list { display: grid; gap: 8px; margin-top: 10px; }
.resource-list__row { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.resource-list__row > div { display: grid; gap: 3px; min-width: 0; }
.resource-list__row strong { overflow: hidden; color: var(--wb-text); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.resource-list__row div span, .resource-list__row > span { color: var(--wb-text-muted); font-size: 10px; }
.resource-list__row > span { flex: 0 0 auto; }
.resource-switch-list { display: grid; gap: 5px; margin-top: 10px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); color: var(--wb-text-muted); font-size: 10px; }
.resource-switch-list span { color: var(--wb-text-secondary); font: 9px var(--font-mono, monospace); }
.sidebar-empty { margin: 10px 0 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1.5; }
</style>
