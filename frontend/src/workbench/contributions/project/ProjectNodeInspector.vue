<template>
  <InspectorFrame :title="graphNode.name" :historical="historical">
    <InspectorSection title="Node" :badge="graphNode.identityQuality || 'unproven'">
      <InspectorPropertyList :rows="[
        { label: 'title', value: graphNode.name },
        { label: 'semanticTaskKey', value: graphNode.semanticTaskKey, code: true },
        { label: 'acgNodeId', value: graphNode.acgNodeId, code: true },
        { label: 'taskId', value: graphNode.taskId, code: true },
        { label: 'status', value: graphNode.status, code: true },
        { label: 'attemptId', value: graphNode.attemptId, code: true },
        { label: 'artifacts', value: graphNode.artifactCount || 0 }
      ]" />
    </InspectorSection>
  </InspectorFrame>
</template>

<script setup lang="ts">
import type { WorkspaceGraphNode } from '@/services/api/agentos'
import InspectorFrame from '@/components/workbench/InspectorFrame.vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

defineProps<{
  graphNode: WorkspaceGraphNode
  historical: boolean
}>()
</script>
