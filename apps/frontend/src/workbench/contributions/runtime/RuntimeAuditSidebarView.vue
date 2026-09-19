<template>
  <div class="sidebar-view-stack">
    <InspectorSection title="审计状态" :badge="audit?.provenanceStatus || '未观测'">
      <InspectorPropertyList :rows="[
        { label: 'provenance', value: audit?.provenanceStatus || '未观测' },
        { label: 'evidence', value: audit?.evidenceCount ?? '未观测' },
        { label: 'contract', value: audit ? audit.contractViolationCount : '未观测' },
        { label: 'recovery', value: audit ? audit.recoveryCount : '未观测' },
        { label: 'review', value: audit?.reviewCount ?? '未观测' }
      ]" />
      <p v-if="!audit && !runtimeObservation" class="sidebar-empty">未观测到审计或 Provenance 数据。</p>
    </InspectorSection>

    <InspectorSection title="问题摘要" :badge="String(relatedProblems.length)">
      <div v-if="relatedProblems.length" class="problem-list">
        <div v-for="problem in relatedProblems" :key="`${problem.source}:${problem.code}:${problem.message}`" class="problem-list__item">
          <strong>{{ problem.code }}</strong>
          <span>{{ problem.message }}</span>
          <small>{{ problem.source }}</small>
        </div>
      </div>
      <p v-else class="sidebar-empty">没有已观测的问题。</p>
    </InspectorSection>

    <InspectorSection title="恢复审计" :badge="recoveryOutcome ? '已记录' : '未观测'">
      <pre v-if="recoveryOutcome" class="structured-value">{{ formatValue(recoveryOutcome) }}</pre>
      <p v-else class="sidebar-empty">当前 Run 没有恢复结果。</p>
      <div v-if="patchRefs.length" class="reference-block">
        <div class="reference-block__heading"><strong>GraphPatch 引用</strong><span>{{ patchRefs.length }}</span></div>
        <code v-for="reference in patchRefs" :key="reference" class="reference-item">{{ reference }}</code>
      </div>
    </InspectorSection>

    <InspectorSection title="恢复轨迹" :badge="String(recoveryEvents.length)">
      <div v-if="recoveryEvents.length" class="event-list" aria-label="恢复与契约异常轨迹">
        <article v-for="event in recoveryEvents" :key="event.eventId" class="event-list__item" :class="event.eventType">
          <div class="event-list__heading">
            <strong>{{ recoveryLabel(event.eventType) }}</strong>
            <time>{{ formatDate(event.timestamp) }}</time>
          </div>
          <code v-if="event.stepId">{{ event.stepId }}</code>
          <span>{{ event.observation || eventSummary(event) }}</span>
          <small v-if="event.payload.strategy || event.payload.faultType">
            <template v-if="event.payload.strategy">策略：{{ event.payload.strategy }}</template>
            <template v-if="event.payload.faultType"> · 故障类型：{{ event.payload.faultType }}</template>
          </small>
          <small>event {{ event.eventId }}</small>
        </article>
      </div>
      <p v-else class="sidebar-empty">本次运行未发生恢复或契约异常。</p>
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import type { RuntimeObservation, RuntimeTraceObservation } from '@/workbench/runtime/observation'
import type { WorkbenchInspectorContext } from '@/workbench/types'

const props = defineProps<{
  context: WorkbenchInspectorContext
  runtimeObservation: RuntimeObservation | null
}>()

const audit = computed(() => props.runtimeObservation?.audit || null)
const operational = computed(() => props.runtimeObservation?.operational || null)
const recoveryOutcome = computed(() => operational.value?.recoveryOutcome || null)
const patchRefs = computed(() => props.runtimeObservation?.patchRefs || [])
const recoveryEvents = computed(() => {
  const events = [
    ...(props.runtimeObservation?.recoveryTrace || []),
    ...(props.runtimeObservation?.scheduleTrace || []),
    ...(props.runtimeObservation?.contractViolations || [])
  ]
  const seen = new Set<string>()
  return events
    .filter(event => {
      if (seen.has(event.eventId)) return false
      seen.add(event.eventId)
      return true
    })
    .sort((left, right) => String(right.timestamp || '').localeCompare(String(left.timestamp || '')))
})
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
const formatValue = (value: unknown) => {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '时间未观测'
const eventSummary = (event: RuntimeTraceObservation) => event.payload.message || event.payload.reason || event.eventType
const recoveryLabel = (eventType: string) => ({
  step_failed: '步骤失败',
  run_recovered: '检查点恢复',
  run_degraded: '降级交付',
  contract_violation: '契约异常'
}[eventType] || eventType)
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.problem-list { display: grid; gap: 10px; }
.problem-list__item { display: grid; gap: 3px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.problem-list__item:first-child { padding-top: 0; border-top: 0; }
.problem-list__item strong { color: var(--wb-warning); font: 10px var(--font-mono, monospace); }
.problem-list__item span { color: var(--wb-text-secondary); font-size: 11px; line-height: 1.45; }
.problem-list__item small { color: var(--wb-text-muted); font-size: 10px; }
.structured-value { max-height: 220px; margin: 0; padding: 8px; overflow: auto; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 9px/1.5 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.reference-block { display: grid; gap: 6px; margin-top: 10px; }
.reference-block__heading { display: flex; align-items: baseline; justify-content: space-between; color: var(--wb-text-secondary); font-size: 10px; }
.reference-block__heading span { color: var(--wb-text-muted); font: 9px var(--font-mono, monospace); }
.reference-item { min-width: 0; overflow-wrap: anywhere; padding: 5px 7px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 9px/1.4 var(--font-mono, monospace); }
.event-list { display: grid; gap: 8px; }
.event-list__item { display: grid; gap: 5px; min-width: 0; padding: 8px 9px; border: 1px solid var(--wb-border-soft); border-left: 2px solid var(--wb-text-muted); border-radius: var(--wb-radius-sm); background: var(--wb-surface-inset); }
.event-list__item.run_recovered, .event-list__item.run_degraded { border-left-color: var(--wb-retry); }
.event-list__item.step_failed, .event-list__item.contract_violation { border-left-color: var(--wb-danger); }
.event-list__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.event-list__heading strong { color: var(--wb-text); font-size: 10px; }
.event-list__heading time, .event-list__item small { color: var(--wb-text-muted); font: 9px/1.4 var(--font-mono, monospace); }
.event-list__item > code { overflow-wrap: anywhere; color: var(--wb-accent); font: 9px/1.4 var(--font-mono, monospace); }
.event-list__item > span { color: var(--wb-text-secondary); font-size: 10px; line-height: 1.4; overflow-wrap: anywhere; }
.sidebar-empty { margin: 10px 0 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1.5; }
</style>
