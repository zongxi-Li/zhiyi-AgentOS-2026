<template>
  <InspectorSection title="Execution" :badge="entry.status || 'pending'">
    <InspectorPropertyList :rows="[
      { label: 'status', value: entry.status, code: true },
      { label: 'attemptCount', value: entry.attemptCount ?? 0 },
      { label: 'latestAttemptId', value: entry.latestAttemptId, code: true },
      { label: 'runtimeStatus', value: runtimeStatus, code: true }
    ]" />
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceEntry } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{ entry: WorkspaceEntry }>()
const runtimeStatus = computed(() => String(props.entry.metadata?.runtimeStatus || '未观测'))
</script>
