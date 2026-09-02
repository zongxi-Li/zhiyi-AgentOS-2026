<template>
  <InspectorSection title="Resource" :badge="resourceObservation ? 'runtime observation' : 'not observed'">
    <InspectorPropertyList :rows="[
      { label: 'runId', value: resourceObservation?.runId || runId, code: true },
      { label: 'attempts', value: resourceObservation?.attemptCount ?? '未观测' },
      { label: 'bound attempts', value: resourceObservation ? resourceObservation.bindings.length : '未观测' },
      { label: 'source', value: resourceObservation?.source || '未观测' }
    ]" />

    <div v-if="resourceObservation?.bindings.length" class="resource-binding-list">
      <article v-for="resource in boundResources" :key="resource.resourceId" class="resource-binding-row">
        <div class="resource-binding-row__heading">
          <strong>{{ resource.resourceId }}</strong>
          <span>{{ tierLabel(resource.deploymentTier) }} · {{ healthLabel(resource.health) }}</span>
        </div>
        <div class="resource-binding-row__meta">
          <span>Agent {{ resource.agentId }}</span>
          <span>Model {{ resource.modelId }}</span>
          <span>{{ resource.attemptCount }} attempts</span>
          <span>Latency {{ formatMetric(resource.latencyMs, 'ms') }}</span>
        </div>
        <div v-if="resource.placementReasons.length" class="resource-reasons">
          <span v-for="reason in resource.placementReasons" :key="reason">{{ reason }}</span>
        </div>
      </article>
    </div>
    <div v-if="resourceObservation?.failoverEvents?.length" class="resource-failover-list" aria-label="端边云切换记录">
      <strong>端边云切换记录</strong>
      <article v-for="event in resourceObservation.failoverEvents" :key="event.eventId" class="resource-failover-row">
        <span>{{ formatDate(event.timestamp) }}</span>
        <p>{{ failoverSummary(event) }}</p>
      </article>
    </div>
    <p v-if="!resourceObservation?.bindings.length" class="resource-empty">{{ resourceObservation ? '当前 Run 没有可证明的资源绑定。' : '未观测到 Run Resource。' }}</p>
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ResourceFailoverObservation, ResourceObservation } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{
  runId: string | null
  resourceObservation: ResourceObservation | null
}>()

const healthLabel = (value: string | null) => ({
  unknown: 'Unknown / 未知',
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Offline'
}[value || 'unknown'] || value || 'Unknown / 未知')

const boundResources = computed(() => {
  const observation = props.resourceObservation
  if (!observation) return []
  const grouped = new Map<string, {
    resourceId: string
    agentId: string
    modelId: string
    attemptCount: number
    health: string
    deploymentTier: string | null
    placementReasons: string[]
    latencyMs: number | null | undefined
  }>()
  for (const binding of observation.bindings) {
    const profile = observation.items.find(item => item.profile.resourceId === binding.resourceId)
    const existing = grouped.get(binding.resourceId)
    if (existing) {
      existing.attemptCount += 1
      continue
    }
    grouped.set(binding.resourceId, {
      resourceId: binding.resourceId,
      agentId: binding.agentId,
      modelId: binding.modelId,
      attemptCount: 1,
      health: profile?.snapshot.healthStatus || 'unknown',
      deploymentTier: binding.deploymentTier || profile?.profile.deploymentTier || null,
      placementReasons: binding.placementReasons,
      latencyMs: profile?.snapshot.latencyMs
    })
  }
  return [...grouped.values()]
})

const tierLabel = (value?: string | null) => ({
  local: '本地', terminal: '端侧', edge: '边缘', cloud: '云端'
}[value || ''] || value || '未分层')

const formatMetric = (value: number | null | undefined, unit: string) => (
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)} ${unit}` : '未观测'
)

const formatDate = (value: string | null) => {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

const failoverSummary = (event: ResourceFailoverObservation) => {
  const failed = event.failedResources.map(item => item.resourceId).join('、')
  const retry = event.retryStepIds.join('、') || '原步骤'
  return `${failed} 失效，步骤 ${retry} 重新调度`
}
</script>

<style scoped>
.resource-binding-list { margin-top: 8px; border-top: 1px solid var(--border-light); }
.resource-binding-row { padding: 9px 0; border-bottom: 1px solid var(--border-light); }
.resource-binding-row__heading, .resource-binding-row__meta { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.resource-binding-row__heading strong { min-width: 0; overflow: hidden; color: var(--text-primary); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.resource-binding-row__heading span { flex: 0 0 auto; color: var(--text-muted); font-size: 10px; }
.resource-binding-row__meta { justify-content: flex-start; margin-top: 4px; color: var(--text-muted); font-size: 10px; flex-wrap: wrap; }
.resource-reasons { display: flex; gap: 5px; margin-top: 6px; flex-wrap: wrap; }
.resource-reasons span { padding: 2px 5px; border: 1px solid var(--border-light); color: var(--text-muted); font: 9px var(--font-mono, monospace); }
.resource-failover-list { display: grid; gap: 7px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-light); color: var(--text-muted); font-size: 10px; }
.resource-failover-row { display: grid; gap: 3px; padding: 7px 8px; border-left: 2px solid var(--warning, #a36a16); background: color-mix(in srgb, var(--warning, #a36a16) 8%, transparent); }
.resource-failover-row p { margin: 0; color: var(--text-secondary); line-height: 1.5; }
.resource-empty { margin: 10px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
</style>
