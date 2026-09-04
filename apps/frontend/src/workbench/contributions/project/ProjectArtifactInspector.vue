<template>
  <InspectorSection title="Artifact" :badge="available ? undefined : 'missing'">
    <button class="inspector-link" type="button" :disabled="!canLocateGraph" @click="emit('locateGraph')">在图中定位</button>
    <InspectorPropertyList :rows="[
      { label: 'semanticTaskKey', value: entry.semanticTaskKey, code: true },
      { label: 'artifactKey', value: entry.artifactKey, code: true },
      { label: 'artifactId', value: entry.artifactId, code: true },
      { label: 'producerAttemptId', value: entry.attemptId, code: true },
      { label: 'runId', value: entry.runId || runId, code: true },
      { label: 'acgNodeId', value: entry.acgNodeId, code: true },
      { label: 'mediaType', value: entry.mediaType, code: true },
      { label: 'checksum', value: entry.checksum || '由 ContentManifest 提供', code: true },
      { label: 'disposition', value: entry.disposition, code: true },
      { label: 'sourceRunId', value: entry.sourceRunId, code: true }
    ]" />
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceEntry } from '@/services/api/agentos'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'

const props = defineProps<{
  entry: WorkspaceEntry
  available: boolean
  runId: string | null
}>()

const emit = defineEmits<{ locateGraph: [] }>()
const canLocateGraph = computed(() => props.available && props.entry.identityQuality !== 'legacy' && Boolean(props.entry.semanticTaskKey))
</script>

<style scoped>
.inspector-link { margin: 0 0 10px; padding: 0; border: 0; color: var(--primary-color); background: transparent; cursor: pointer; font-size: 11px; }
.inspector-link:disabled { color: var(--text-disabled); cursor: not-allowed; }
</style>
