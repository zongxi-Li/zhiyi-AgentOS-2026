<template>
  <div class="sidebar-view-stack">
    <InspectorSection title="审计状态" :badge="audit?.provenanceStatus || '未观测'">
      <InspectorPropertyList :rows="[
        { label: 'provenance', value: audit?.provenanceStatus || '未观测' },
        { label: 'evidence', value: audit?.evidenceCount ?? '未观测' },
        { label: 'contract', value: audit ? audit.contractViolationCount : '未观测' },
        { label: 'recovery', value: audit ? audit.recoveryCount : '未观测' },
        { label: 'review', value: '未观测' }
      ]" />
      <p v-if="!audit && !runtimeObservation" class="sidebar-empty">未观测到审计或 Provenance 数据。</p>
    </InspectorSection>

    <InspectorSection title="问题摘要" :badge="String(relatedProblems.length)">
      <div v-if="relatedProblems.length" class="problem-list">
        <div v-for="problem in relatedProblems.slice(0, 3)" :key="`${problem.source}:${problem.code}:${problem.message}`" class="problem-list__item">
          <strong>{{ problem.code }}</strong>
          <span>{{ problem.message }}</span>
          <small>{{ problem.source }}</small>
        </div>
      </div>
      <p v-else class="sidebar-empty">没有已观测的问题。</p>
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { WorkbenchInspectorContext } from '@/workbench/types'

const props = defineProps<{
  context: WorkbenchInspectorContext
  runtimeObservation: RuntimeObservation | null
}>()

const audit = computed(() => props.runtimeObservation?.audit || null)
const targetIds = computed(() => new Set([
  props.context.selectedAcgNodeId,
  props.context.graphNode?.acgNodeId,
  props.context.graphNode?.taskId,
  props.context.entry?.acgNodeId,
  props.context.entry?.taskId
].filter((value): value is string => Boolean(value))))
const relatedProblems = computed(() => {
  const problems = props.runtimeObservation?.problems || []
  const targets = targetIds.value
  if (!targets.size) return problems
  const related = problems.filter(problem => !problem.targetStepId || targets.has(problem.targetStepId))
  return related.length ? related : problems
})
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.problem-list { display: grid; gap: 10px; }
.problem-list__item { display: grid; gap: 3px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.problem-list__item:first-child { padding-top: 0; border-top: 0; }
.problem-list__item strong { color: var(--wb-warning); font: 10px var(--font-mono, monospace); }
.problem-list__item span { color: var(--wb-text-secondary); font-size: 11px; line-height: 1.45; }
.problem-list__item small { color: var(--wb-text-muted); font-size: 10px; }
.sidebar-empty { margin: 10px 0 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1.5; }
</style>
