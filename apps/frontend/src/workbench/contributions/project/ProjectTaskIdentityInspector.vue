<template>
  <InspectorSection title="Identity" :badge="entry.identityQuality || 'unproven'">
    <InspectorPropertyList :rows="[
      { label: 'semanticTaskKey', value: entry.semanticTaskKey, code: true },
      { label: 'taskId', value: entry.taskId, code: true },
      { label: 'logicalRole', value: entry.logicalRole },
      { label: 'acgNodeId', value: entry.acgNodeId, code: true }
    ]" />
  </InspectorSection>
</template>

<script setup lang="ts">
import type { WorkspaceEntry } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

defineProps<{ entry: WorkspaceEntry }>()
</script>
