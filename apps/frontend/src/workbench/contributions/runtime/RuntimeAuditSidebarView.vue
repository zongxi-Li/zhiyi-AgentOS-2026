<template>
  <div class="sidebar-view-stack">
    <InspectorSection title="审计状态" :badge="audit?.provenanceStatus || '未观测'">
      <dl v-if="audit" class="audit-metrics">
        <div><dt>证据数量</dt><dd>{{ audit.evidenceCount }}</dd></div>
        <div><dt>契约异常</dt><dd>{{ audit.contractViolationCount }}</dd></div>
        <div><dt>恢复次数</dt><dd>{{ audit.recoveryCount }}</dd></div>
        <div><dt>审核次数</dt><dd>{{ audit.reviewCount ?? '未观测' }}</dd></div>
      </dl>
      <p v-if="!audit && !runtimeObservation" class="sidebar-empty">审计和来源记录尚未获取。</p>
    </InspectorSection>

    <InspectorSection title="问题摘要" :badge="String(relatedProblems.length)">
      <div v-if="relatedProblems.length" class="problem-list">
        <div v-for="problem in relatedProblems" :key="`${problem.source}:${problem.code}:${problem.message}`" class="problem-list__item">
          <strong>{{ problem.message }}</strong>
          <div class="problem-list__meta"><code>{{ problem.code }}</code><small>{{ problem.source }}</small></div>
        </div>
      </div>
      <p v-else class="sidebar-empty">{{ runtimeObservation ? '当前快照没有报告问题。' : '审计数据尚未获取，暂时无法判断是否有问题。' }}</p>
    </InspectorSection>

    <InspectorSection title="恢复审计" :badge="recoveryOutcome ? '已记录' : '未观测'">
      <InspectorDetails v-if="recoveryOutcome" text-toggle title="恢复结果原始记录"><pre class="structured-value">{{ formatValue(recoveryOutcome) }}</pre></InspectorDetails>
      <p v-else class="sidebar-empty">当前快照没有记录恢复结果。</p>
      <div v-if="patchRefs.length" class="reference-block">
        <div class="reference-block__heading"><strong>执行图修订引用</strong><span>{{ patchRefs.length }}</span></div>
        <code v-for="reference in patchRefs" :key="reference" class="reference-item">{{ reference }}</code>
      </div>
    </InspectorSection>

    <InspectorSection title="恢复与调度记录" :badge="String(recoveryEvents.length)">
      <InspectorDetails v-if="recoveryEvents.length" text-toggle title="恢复与调度明细"><div class="event-list" aria-label="恢复与契约异常轨迹">
        <article v-for="event in recoveryEvents" :key="event.eventId" class="event-list__item" :class="event.eventType">
          <div class="event-list__heading">
            <strong>{{ recoveryLabel(event.eventType) }}</strong>
            <time>{{ formatDate(event.timestamp) }}</time>
          </div>
          <code v-if="event.stepId">{{ event.stepId }}</code>
          <span>{{ inspectorEventSummary(String(event.observation || eventSummary(event))) }}</span>
          <small v-if="event.payload.strategy || event.payload.faultType">
            <template v-if="event.payload.strategy">策略：{{ event.payload.strategy }}</template>
            <template v-if="event.payload.faultType"> · 故障类型：{{ event.payload.faultType }}</template>
          </small>
          <InspectorDetails text-toggle title="事件技术详情"><code>{{ event.eventType }} · {{ event.eventId }}</code></InspectorDetails>
        </article>
      </div></InspectorDetails>
      <p v-else class="sidebar-empty">{{ runtimeObservation ? '当前快照没有恢复、调度或契约异常记录。' : '恢复与调度数据尚未获取。' }}</p>
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { inspectorEventLabel, inspectorEventSummary } from '@/workbench/runtime/inspectorPresentation'
import InspectorDetails from '@/components/workbench/InspectorDetails.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import type { RuntimeObservation, RuntimeTraceObservation } from '@/workbench/runtime/observation'
import type { WorkbenchInspectorContext } from '@/workbench/types'

const props = defineProps<{
  context: WorkbenchInspectorContext
  runtimeObservation: RuntimeObservation | null
}>()

const audit = computed(() => props.runtimeObservation?.audit || null)
const recoveryOutcome = computed(() => {
  const operational = props.runtimeObservation?.operational
  return operational && 'recoveryOutcome' in operational ? operational.recoveryOutcome : null
})
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
}[eventType] || inspectorEventLabel(eventType))
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.audit-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(75px, 1fr)); gap: 6px; margin: 0; }
.audit-metrics > div, .problem-list__item { min-width: 0; padding: 8px 10px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-md); background: var(--wb-surface-inset); }
.audit-metrics dt { color: var(--wb-text-muted); font-size: 11px; }
.audit-metrics dd { margin: 3px 0 0; color: var(--wb-text); font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.problem-list { display: grid; gap: 6px; }
.problem-list__item { display: grid; gap: 4px; }
.problem-list__meta { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; }
.problem-list__item strong { color: var(--wb-text); font: 500 13px/1.6 var(--font-sans, sans-serif); }
.problem-list__item code { color: var(--wb-text-muted); font: 11px/1.6 var(--font-mono, monospace); }
.problem-list__item span { color: var(--wb-text-secondary); font-size: 12px; line-height: 1.45; }
.problem-list__item small { color: var(--wb-text-muted); font-size: 12px; }
.structured-value { max-height: 220px; margin: 0; padding: 8px; overflow: auto; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 9px/1.5 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.reference-block { display: grid; gap: 6px; margin-top: 10px; }
.reference-block__heading { display: flex; align-items: baseline; justify-content: space-between; color: var(--wb-text-secondary); font-size: 12px; }
.reference-block__heading span { color: var(--wb-text-muted); font: 9px var(--font-mono, monospace); }
.reference-item { min-width: 0; overflow-wrap: anywhere; padding: 5px 7px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 9px/1.4 var(--font-mono, monospace); }
.event-list { display: grid; gap: 8px; }
.event-list__item { display: grid; gap: 5px; min-width: 0; padding: 8px 9px; border: 1px solid var(--wb-border-soft); border-left: 2px solid var(--wb-text-muted); border-radius: var(--wb-radius-sm); background: var(--wb-surface-inset); }
.event-list__item.run_recovered, .event-list__item.run_degraded { border-left-color: var(--wb-retry); }
.event-list__item.step_failed, .event-list__item.contract_violation { border-left-color: var(--wb-danger); }
.event-list__heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 4px 8px; }
.event-list__heading strong { color: var(--wb-text); font-size: 12px; }
.event-list__heading time, .event-list__item small { color: var(--wb-text-muted); font: 9px/1.4 var(--font-mono, monospace); }
.event-list__item > code { overflow-wrap: anywhere; color: var(--wb-accent); font: 9px/1.4 var(--font-mono, monospace); }
.event-list__item > span { color: var(--wb-text-secondary); font-size: 12px; line-height: 1.4; overflow-wrap: anywhere; }
.sidebar-empty { margin: 10px 0 0; color: var(--wb-text-muted); font-size: 12px; line-height: 1.5; }
</style>
