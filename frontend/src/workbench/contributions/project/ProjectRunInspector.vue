<template>
  <InspectorFrame :title="entry.name" :historical="historical">
    <InspectorSection title="Run" :badge="entry.status || undefined">
      <InspectorPropertyList :rows="[
        { label: 'runId', value: entry.runId, code: true },
        { label: 'status', value: entry.status, code: true },
        { label: 'createdAt', value: entry.createdAt },
        { label: 'completedAt', value: entry.completedAt },
        { label: 'sourceRunId', value: entry.sourceRunId, code: true }
      ]" />
    </InspectorSection>
  </InspectorFrame>
</template>

<script setup lang="ts">
import type { WorkspaceEntry } from '@/services/api/agentos'
import InspectorFrame from '@/components/workbench/InspectorFrame.vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

defineProps<{
  entry: WorkspaceEntry
  historical: boolean
}>()
</script>
