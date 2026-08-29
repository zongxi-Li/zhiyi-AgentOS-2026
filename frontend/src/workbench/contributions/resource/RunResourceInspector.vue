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
          <span>{{ healthLabel(resource.health) }}</span>
        </div>
        <div class="resource-binding-row__meta">
          <span>Agent {{ resource.agentId }}</span>
          <span>Model {{ resource.modelId }}</span>
          <span>{{ resource.attemptCount }} attempts</span>
        </div>
      </article>
    </div>
    <p v-else class="resource-empty">{{ resourceObservation ? '当前 Run 没有可证明的资源绑定。' : '未观测到 Run Resource。' }}</p>
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ResourceObservation } from '@/services/api/agentos'
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
      health: profile?.snapshot.healthStatus || 'unknown'
    })
  }
  return [...grouped.values()]
})
</script>

<style scoped>
.resource-binding-list { margin-top: 8px; border-top: 1px solid var(--border-light); }
.resource-binding-row { padding: 9px 0; border-bottom: 1px solid var(--border-light); }
.resource-binding-row__heading, .resource-binding-row__meta { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.resource-binding-row__heading strong { min-width: 0; overflow: hidden; color: var(--text-primary); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.resource-binding-row__heading span { flex: 0 0 auto; color: var(--text-muted); font-size: 10px; }
.resource-binding-row__meta { justify-content: flex-start; margin-top: 4px; color: var(--text-muted); font-size: 10px; flex-wrap: wrap; }
.resource-empty { margin: 10px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
</style>
