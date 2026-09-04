<template>
  <InspectorSection title="Artifacts" :badge="String(artifacts)">
    <InspectorPropertyList :rows="[
      { label: 'artifactCount', value: entry.artifactCount ?? 0 },
      { label: 'note', value: artifacts ? '在 TaskEditor 中打开真实 Artifact' : '当前 Task 尚无 Artifact' }
    ]" />
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceEntry } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{ entry: WorkspaceEntry }>()

const artifacts = computed(() => props.entry.artifactCount ?? 0)
</script>
