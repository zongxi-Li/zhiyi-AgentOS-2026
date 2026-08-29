<template>
  <InspectorSection title="Resource" :badge="binding ? healthLabel(resourceHealth) : 'not observed'">
    <InspectorPropertyList :rows="[
      { label: 'resourceId', value: binding?.resourceId || '未观测', code: true },
      { label: 'agentId', value: binding?.agentId || '未观测', code: true },
      { label: 'modelId', value: binding?.modelId || '未观测', code: true },
      { label: 'bindingId', value: binding?.bindingId || '未观测', code: true },
      { label: 'attemptId', value: binding?.attemptId || graphNode.attemptId, code: true },
      { label: 'health', value: binding ? healthLabel(resourceHealth) : '未观测' }
    ]" />
    <p v-if="!binding" class="resource-empty">当前节点没有可证明的 ExecutionBinding。</p>
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ResourceBindingObservation, ResourceObservation, WorkspaceGraphNode } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{
  graphNode: WorkspaceGraphNode
  resourceObservation: ResourceObservation | null
}>()

const binding = computed<ResourceBindingObservation | null>(() => {
  const observation = props.resourceObservation
  if (!observation) return null
  return observation.bindings.find(item => (
    (props.graphNode.attemptId && item.attemptId === props.graphNode.attemptId)
    || (item.acgNodeId === props.graphNode.acgNodeId && item.semanticTaskKey === props.graphNode.semanticTaskKey)
  )) || null
})

const resourceHealth = computed(() => {
  const resourceId = binding.value?.resourceId
  return props.resourceObservation?.items.find(item => item.profile.resourceId === resourceId)?.snapshot.healthStatus || 'unknown'
})

const healthLabel = (value: string) => ({
  unknown: 'Unknown / 未知',
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Offline'
}[value] || value || 'Unknown / 未知')
</script>

<style scoped>
.resource-empty { margin: 10px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
</style>
