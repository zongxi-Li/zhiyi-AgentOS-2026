<template>
  <InspectorSection title="Mission" badge="projection">
    <InspectorPropertyList :rows="[
      { label: 'missionId', value: missionId, code: true },
      { label: 'activeRun', value: runId, code: true },
      { label: 'mode', value: 'read-only', code: true }
    ]" />
  </InspectorSection>
</template>

<script setup lang="ts">
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

defineProps<{
  missionId: string
  runId: string | null
}>()
</script>
