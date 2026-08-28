<template>
  <aside class="runtime-inspector" aria-label="Workspace Inspector">
    <header class="runtime-inspector__header">
      <div>
        <span>INSPECTOR</span>
        <strong>{{ inspectorTitle }}</strong>
      </div>
      <span v-if="isHistorical" class="runtime-inspector__badge">Historical</span>
    </header>

    <div v-if="!entry && !graphNode" class="runtime-inspector__empty">选择一个 Workspace entry 或图节点查看属性。</div>

    <section v-else-if="entry?.kind === 'artifact'" class="inspector-section">
      <div class="inspector-section__heading"><strong>Artifact</strong><span v-if="!available">missing</span></div>
      <button class="inspector-link" type="button" :disabled="!canLocateGraph" @click="emit('locateGraph')">在图中定位</button>
      <dl class="property-list">
        <PropertyRow label="semanticTaskKey" :value="entry.semanticTaskKey" code />
        <PropertyRow label="artifactKey" :value="entry.artifactKey" code />
        <PropertyRow label="artifactId" :value="entry.artifactId" code />
        <PropertyRow label="producerAttemptId" :value="entry.attemptId" code />
        <PropertyRow label="runId" :value="entry.runId || runId" code />
        <PropertyRow label="acgNodeId" :value="entry.acgNodeId" code />
        <PropertyRow label="mediaType" :value="entry.mediaType" code />
        <PropertyRow label="checksum" :value="entry.checksum || '由 ContentManifest 提供'" code />
        <PropertyRow label="disposition" :value="entry.disposition" code />
        <PropertyRow label="sourceRunId" :value="entry.sourceRunId" code />
      </dl>
    </section>

    <section v-else-if="entry?.kind === 'run'" class="inspector-section">
      <div class="inspector-section__heading"><strong>Run</strong><span>{{ entry.status }}</span></div>
      <dl class="property-list">
        <PropertyRow label="runId" :value="entry.runId" code />
        <PropertyRow label="status" :value="entry.status" code />
        <PropertyRow label="createdAt" :value="entry.createdAt" />
        <PropertyRow label="completedAt" :value="entry.completedAt" />
        <PropertyRow label="sourceRunId" :value="entry.sourceRunId" code />
      </dl>
    </section>

    <section v-else-if="graphNode" class="inspector-section">
      <div class="inspector-section__heading"><strong>Graph node</strong><span>{{ graphNode.identityQuality || 'unproven' }}</span></div>
      <dl class="property-list">
        <PropertyRow label="acgNodeId" :value="graphNode.acgNodeId" code />
        <PropertyRow label="semanticTaskKey" :value="graphNode.semanticTaskKey" code />
        <PropertyRow label="taskId" :value="graphNode.taskId" code />
        <PropertyRow label="nodeType" :value="graphNode.nodeType" code />
        <PropertyRow label="name" :value="graphNode.name" />
        <PropertyRow label="runId" :value="runId" code />
      </dl>
    </section>

    <section v-else class="inspector-section">
      <div class="inspector-section__heading"><strong>Mission</strong><span>projection</span></div>
      <dl class="property-list">
        <PropertyRow label="missionId" :value="missionId" code />
        <PropertyRow label="activeRun" :value="runId" code />
        <PropertyRow label="mode" value="read-only" code />
      </dl>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed, defineComponent, h } from 'vue'
import type { WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'

const props = defineProps<{
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
  available: boolean
  runId: string | null
  missionId: string
  historical: boolean
}>()

const emit = defineEmits<{ locateGraph: [] }>()

const PropertyRow = defineComponent({
  props: { label: { type: String, required: true }, value: { type: [String, Number], default: undefined }, code: Boolean },
  setup(rowProps) {
    return () => h('div', { class: 'property-row' }, [
      h('dt', rowProps.label),
      h('dd', { class: rowProps.code ? 'is-code' : undefined }, rowProps.value == null || rowProps.value === '' ? '—' : String(rowProps.value))
    ])
  }
})

const isHistorical = computed(() => props.historical)
const inspectorTitle = computed(() => props.entry?.name || props.graphNode?.name || 'Mission')
const canLocateGraph = computed(() => props.available && props.entry?.kind === 'artifact' && props.entry.identityQuality !== 'legacy' && Boolean(props.entry.semanticTaskKey))
</script>

<style scoped>
.runtime-inspector { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; background: var(--bg-card); color: var(--text-primary); }
.runtime-inspector__header { display: flex; justify-content: space-between; gap: 12px; padding: 16px 15px 13px; border-bottom: 1px solid var(--border-light); }
.runtime-inspector__header span:first-child { display: block; color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.runtime-inspector__header strong { display: block; max-width: 190px; margin-top: 4px; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.runtime-inspector__badge { align-self: flex-start; color: var(--warning); font: 10px var(--font-mono, monospace); }
.runtime-inspector__empty { padding: 22px 15px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }
.inspector-section { min-height: 0; overflow: auto; padding: 14px 15px; }
.inspector-section__heading { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 10px; color: var(--text-secondary); font: 10px var(--font-mono, monospace); text-transform: uppercase; }
.inspector-section__heading strong { color: var(--text-primary); font: 12px var(--font-sans, sans-serif); text-transform: none; }
.inspector-link { margin: 0 0 10px; padding: 0; border: 0; color: var(--primary-color); background: transparent; cursor: pointer; font-size: 11px; }
.inspector-link:disabled { color: var(--text-disabled); cursor: not-allowed; }
.property-list { margin: 0; }
.property-row { display: grid; grid-template-columns: minmax(92px, 42%) minmax(0, 1fr); gap: 10px; min-height: 30px; padding: 7px 0; border-bottom: 1px solid color-mix(in srgb, var(--border-light) 70%, transparent); font-size: 11px; }
.property-row dt { overflow: hidden; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; }
.property-row dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--text-secondary); text-align: right; }
.property-row dd.is-code { color: var(--text-primary); font: 10px var(--font-mono, monospace); }
</style>
