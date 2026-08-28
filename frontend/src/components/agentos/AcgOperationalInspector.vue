<template>
  <section class="operational-inspector ui-surface" aria-label="ACG 运行详情">
    <el-tabs v-model="activeTab" stretch>
      <el-tab-pane name="runtime">
        <template #label><span class="tab-label"><el-icon><DataAnalysis /></el-icon>运行状态</span></template>
        <AcgLowEntropyMetrics :metrics="view.lowEntropyMetrics" />
        <div class="section-block">
          <header><strong>节点生命周期</strong><span>{{ records.length }}</span></header>
          <p v-if="!records.length" class="empty">暂无 Identity 节点执行记录</p>
          <div v-else class="record-list">
            <article v-for="record in records" :key="record.executionInstanceId">
              <div><strong>{{ record.stepId }}</strong><span class="phase" :class="record.phase">{{ phaseLabel(record.phase) }}</span></div>
              <code :title="record.executionInstanceId">{{ shortId(record.executionInstanceId) }}</code>
              <small>Attempt {{ shortId(record.attemptId) }}<template v-if="record.loopPath.length"> · Loop {{ record.loopPath.join('.') }}</template></small>
              <small v-if="record.commitId">Commit {{ shortId(record.commitId) }}</small>
              <small v-if="record.failureCode" class="failure">{{ record.failureCode }}</small>
            </article>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane name="control">
        <template #label><span class="tab-label"><el-icon><Operation /></el-icon>控制协同</span></template>
        <OperationalSummary :items="controlSummary" />
        <OperationalGroup title="控制 Frame" :items="controlFrames" />
        <OperationalMap title="Loop 迭代" :value="view.operational?.loopIterations || {}" />
        <OperationalMap title="Consensus" :value="view.operational?.consensusResults || {}" />
        <OperationalMap title="Debate" :value="view.operational?.debateSessions || {}" />
      </el-tab-pane>

      <el-tab-pane name="context">
        <template #label><span class="tab-label"><el-icon><Connection /></el-icon>通信上下文</span></template>
        <OperationalSummary :items="contextSummary" />
        <ReferenceGroup title="Communication" :refs="view.operational?.communicationRefs || []" />
        <ReferenceGroup title="Memory" :refs="view.operational?.memoryRefs || []" />
        <ReferenceGroup title="Evidence" :refs="view.operational?.evidenceRefs || []" />
        <OperationalMap title="Lease" :value="view.operational?.leaseStatuses || {}" />
      </el-tab-pane>

      <el-tab-pane name="audit">
        <template #label><span class="tab-label"><el-icon><RefreshRight /></el-icon>恢复审计</span></template>
        <div class="section-block">
          <header><strong>恢复结果</strong></header>
          <pre v-if="view.operational?.recoveryOutcome">{{ formatValue(view.operational.recoveryOutcome) }}</pre>
          <p v-else class="empty">当前 Run 没有恢复结果</p>
        </div>
        <RuntimeAuditTimeline :events="auditEvents" :patch-refs="patchRefs" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, ref, type PropType } from 'vue'
import { Connection, DataAnalysis, Operation, RefreshRight } from '@element-plus/icons-vue'
import type { AcgView, NodeExecutionPhase, TraceEvent } from '@/services/api/workflow'
import AcgLowEntropyMetrics from './AcgLowEntropyMetrics.vue'
import RuntimeAuditTimeline from './RuntimeAuditTimeline.vue'

const props = defineProps<{
  view: AcgView
  auditEvents: TraceEvent[]
  patchRefs: string[]
}>()
const emit = defineEmits<{ 'export-audit': [format: 'json' | 'csv'] }>()
const activeTab = ref('runtime')
const records = computed(() => props.view.operational?.nodeExecutions || [])
const controlFrames = computed(() => props.view.operational?.controlFrames || [])
const controlSummary = computed(() => [
  { label: 'Control Frame', value: controlFrames.value.length },
  { label: 'Loop', value: Object.keys(props.view.operational?.loopIterations || {}).length },
  { label: 'Consensus', value: Object.keys(props.view.operational?.consensusResults || {}).length },
  { label: 'Debate', value: Object.keys(props.view.operational?.debateSessions || {}).length }
])
const contextSummary = computed(() => [
  { label: 'Communication', value: (props.view.operational?.communicationRefs || []).length },
  { label: 'Memory', value: (props.view.operational?.memoryRefs || []).length },
  { label: 'Evidence', value: (props.view.operational?.evidenceRefs || []).length },
  { label: 'Lease', value: Object.keys(props.view.operational?.leaseStatuses || {}).length }
])

const formatValue = (value: unknown) => JSON.stringify(value, null, 2)
const shortId = (value: string) => value.length > 28 ? `${value.slice(0, 14)}...${value.slice(-8)}` : value
const phaseLabel = (phase: NodeExecutionPhase) => ({
  prepared: '已准备', executed: '已执行', audited: '已审计', committed: '已提交',
  waiting_review: '待审核', failed: '失败', cancelled: '已取消'
}[phase])

const emptyText = (title: string) => `暂无 ${title} 数据`
const ReferenceGroup = defineComponent({
  props: { title: { type: String, required: true }, refs: { type: Array as PropType<string[]>, required: true } },
  setup(componentProps) {
    return () => h('div', { class: 'section-block' }, [
      h('header', [h('strong', componentProps.title), h('span', String(componentProps.refs.length))]),
      componentProps.refs.length
        ? h('div', { class: 'reference-list' }, componentProps.refs.map((item, index) =>
          h('article', { class: 'data-card reference-card', key: item }, [
            h('span', { class: 'data-card__index', 'aria-hidden': 'true' }, String(index + 1).padStart(2, '0')),
            h('code', { title: item }, item)
          ])
        ))
        : h('p', { class: 'empty' }, emptyText(componentProps.title))
    ])
  }
})
const OperationalGroup = defineComponent({
  props: { title: { type: String, required: true }, items: { type: Array as PropType<Array<Record<string, unknown>>>, required: true } },
  setup(componentProps) {
    return () => h('div', { class: 'section-block' }, [
      h('header', [h('strong', componentProps.title), h('span', String(componentProps.items.length))]),
      componentProps.items.length
        ? h('div', { class: 'structured-list' }, componentProps.items.map((item, index) =>
          h('article', { class: 'data-card structured-card', key: index }, [
            h('div', { class: 'data-card__heading' }, [
              h('strong', `记录 ${String(index + 1).padStart(2, '0')}`)
            ]),
            h('pre', formatValue(item))
          ])
        ))
        : h('p', { class: 'empty' }, emptyText(componentProps.title))
    ])
  }
})
const OperationalMap = defineComponent({
  props: { title: { type: String, required: true }, value: { type: Object as PropType<Record<string, unknown>>, required: true } },
  setup(componentProps) {
    return () => h('div', { class: 'section-block' }, [
      h('header', [h('strong', componentProps.title), h('span', String(Object.keys(componentProps.value).length))]),
      Object.keys(componentProps.value).length
        ? h('div', { class: 'structured-list' }, Object.entries(componentProps.value).map(([key, value]) =>
          h('article', { class: 'data-card structured-card', key }, [
            h('div', { class: 'data-card__heading' }, [
              h('code', { title: key }, key)
            ]),
            h('pre', formatValue(value))
          ])
        ))
        : h('p', { class: 'empty' }, emptyText(componentProps.title))
    ])
  }
})
const OperationalSummary = defineComponent({
  props: { items: { type: Array as PropType<Array<{ label: string; value: number }>>, required: true } },
  setup(componentProps) {
    return () => h('div', { class: 'operational-summary', 'aria-label': '能力状态摘要' }, componentProps.items.map(item =>
      h('div', { class: ['summary-card', { 'summary-card--active': item.value > 0 }], key: item.label }, [
        h('strong', String(item.value)),
        h('span', item.label)
      ])
    ))
  }
})
</script>

<style scoped>
.operational-inspector { min-width: 0; border-radius: 0; box-shadow: none; font-family: var(--font-sans); }
.operational-inspector :deep(.el-tabs__header) { margin: 0; padding: 12px 12px 0; }
.operational-inspector :deep(.el-tabs__nav-wrap::after) { display: none; }
.operational-inspector :deep(.el-tabs__nav) {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; width: 100%; margin: 0; padding: 4px;
  border: 1px solid color-mix(in srgb, var(--primary-color) 8%, var(--border-light)); border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--bg-input) 88%, var(--bg-card));
}
.operational-inspector :deep(.el-tabs__item) {
  min-width: 0; height: 34px; padding: 0 8px; border: 1px solid transparent; border-radius: var(--radius-control);
  color: var(--text-secondary); font-family: var(--font-sans); font-size: 11px; line-height: 32px;
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}
.operational-inspector :deep(.el-tabs__item:hover:not(.is-active)) {
  border-color: color-mix(in srgb, var(--primary-color) 10%, var(--border-light));
  background: color-mix(in srgb, var(--surface-solid) 82%, transparent); color: var(--text-primary);
}
.operational-inspector :deep(.el-tabs__item.is-active) {
  border-color: color-mix(in srgb, var(--primary-color) 28%, var(--border-light));
  background: var(--surface-solid); color: var(--primary-color); font-weight: 700;
  box-shadow: 0 1px 2px color-mix(in srgb, var(--text-primary) 7%, transparent), 0 0 0 1px color-mix(in srgb, var(--primary-color) 4%, transparent);
}
.operational-inspector :deep(.el-tabs__item:focus-visible) { outline: 2px solid color-mix(in srgb, var(--primary-color) 55%, transparent); outline-offset: 1px; }
.operational-inspector :deep(.el-tabs__active-bar) { display: none; }
.operational-inspector :deep(.el-tabs__content) { padding: 16px; overflow: visible; }
.tab-label { min-width: 0; display: inline-flex; align-items: center; justify-content: center; gap: 5px; font-size: inherit; font-weight: 600; white-space: nowrap; }
.tab-label .el-icon { flex: 0 0 auto; font-size: 13px; }
:deep(.operational-summary) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 2px 0 16px; border-bottom: 1px solid var(--border-light); }
:deep(.summary-card) { min-width: 0; min-height: 64px; display: flex; flex-direction: column; justify-content: center; gap: 5px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--primary-color) 12%, var(--border-light)); border-radius: var(--radius-card); background: color-mix(in srgb, var(--bg-input) 68%, var(--bg-card)); }
:deep(.summary-card strong) { color: #202236; font-size: 21px; font-weight: 750; line-height: 1; letter-spacing: 0; }
:deep(.summary-card span) { overflow-wrap: anywhere; color: #737894; font-size: 11px; line-height: 1.25; }
:deep(.summary-card--active) { border-color: color-mix(in srgb, var(--primary-color) 30%, var(--border-light)); background: color-mix(in srgb, var(--primary-fade) 62%, var(--bg-card)); }
:deep(.summary-card--active strong) { color: #5b61d6; }
:deep(.summary-card:nth-child(2)) { background: color-mix(in srgb, var(--success-fade) 58%, var(--bg-card)); }
:deep(.summary-card:nth-child(2) strong) { color: #3e7e60; }
:deep(.section-block) { display: grid; gap: 9px; padding: 12px 2px; border-bottom: 1px solid var(--border-light); font-family: var(--font-sans); }
:deep(.section-block header), .record-list article > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
:deep(.section-block header strong) { color: var(--text-primary); font-family: var(--font-sans); font-size: 12px; font-weight: 700; line-height: 1.4; }
:deep(.section-block header span), :deep(.empty) { color: var(--text-secondary); font-family: var(--font-sans); font-size: 10px; }
:deep(.empty) { margin: 0; padding: 11px 12px; border: 1px dashed color-mix(in srgb, var(--primary-color) 18%, var(--border-light)); border-radius: var(--radius-card); background: color-mix(in srgb, var(--bg-input) 55%, transparent); color: #8589a0; line-height: 1.45; text-align: center; }
.record-list, :deep(.structured-list), :deep(.reference-list) { display: grid; gap: 7px; }
.record-list article, :deep(.data-card) {
  box-sizing: border-box; min-width: 0; border: 1px solid color-mix(in srgb, var(--primary-color) 8%, var(--border-light));
  border-radius: var(--radius-card); background: color-mix(in srgb, var(--bg-input) 82%, var(--bg-card));
}
.record-list article { display: grid; gap: 4px; padding: 9px 10px; border-left: 2px solid color-mix(in srgb, var(--primary-color) 22%, var(--border-light)); }
.record-list strong { overflow-wrap: anywhere; color: var(--text-primary); font-family: var(--font-sans); font-size: 11px; font-weight: 700; }
.record-list code, .record-list small { overflow-wrap: anywhere; color: var(--text-secondary); font-family: var(--font-mono); font-size: 9px; line-height: 1.45; }
.record-list .failure { color: var(--danger); }
.phase { padding: 2px 7px; border-radius: var(--radius-full); color: var(--primary-color); background: var(--primary-fade); font-size: 9px; }
.phase.committed { color: var(--success); background: var(--success-fade); }
.phase.failed, .phase.cancelled { color: var(--danger); background: var(--danger-fade); }
.phase.waiting_review { color: var(--warning); background: var(--warning-fade); }
:deep(.reference-card) { display: grid; grid-template-columns: 22px minmax(0, 1fr); align-items: start; gap: 7px; padding: 9px 10px; }
:deep(.data-card__index) { padding-top: 1px; color: var(--text-muted); font: 700 9px/1.45 var(--font-mono); }
:deep(.reference-card code) { min-width: 0; overflow-wrap: anywhere; word-break: break-word; color: var(--text-secondary); font: 9px/1.5 var(--font-mono); }
:deep(.structured-card) { overflow: hidden; }
:deep(.data-card__heading) { min-width: 0; padding: 8px 10px 7px; border-bottom: 1px solid var(--border-light); }
:deep(.data-card__heading strong) { color: var(--text-primary); font-family: var(--font-sans); font-size: 10px; font-weight: 700; }
:deep(.data-card__heading code) { display: block; overflow-wrap: anywhere; word-break: break-word; color: var(--text-primary); font: 700 10px/1.45 var(--font-mono); }
:deep(.structured-card pre), pre {
  box-sizing: border-box; max-width: 100%; max-height: 240px; margin: 0; padding: 9px 10px 10px; overflow: auto;
  border: 0; border-radius: 0; background: transparent; color: var(--text-secondary);
  font: 9px/1.6 var(--font-mono); tab-size: 2; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
}
.operational-inspector :deep(.acg-metrics), .operational-inspector :deep(.acg-provenance), .operational-inspector :deep(.runtime-audit-timeline) { border: 0; border-radius: 0; box-shadow: none; }
.operational-inspector { background: transparent; }
:deep(.operational-summary) { grid-template-columns: 1fr; gap: 0; padding: 0; }
:deep(.summary-card) { min-height: 30px; flex-direction: row; align-items: baseline; justify-content: space-between; gap: 8px; padding: 5px 0; border: 0; border-bottom: 1px solid var(--wb-border, var(--border-light)); border-radius: 0; background: transparent; }
:deep(.summary-card strong) { order: 2; color: var(--wb-text, var(--text-primary)); font-size: 11px; font-weight: 720; }
:deep(.summary-card span) { order: 1; color: var(--wb-muted, var(--text-secondary)); font-size: 10px; }
:deep(.summary-card--active), :deep(.summary-card:nth-child(2)), :deep(.summary-card--active strong), :deep(.summary-card:nth-child(2) strong) { background: transparent; color: var(--wb-text, var(--text-primary)); }
:deep(.summary-card--active strong) { color: var(--wb-accent, var(--primary-color)); }
:deep(.section-block) { gap: 6px; padding: 9px 0; }
:deep(.empty) { padding: 9px 0; border: 0; border-radius: 0; background: transparent; text-align: left; }
.record-list, :deep(.structured-list), :deep(.reference-list) { gap: 0; }
.record-list article, :deep(.data-card) { border: 0; border-bottom: 1px solid var(--wb-border, var(--border-light)); border-radius: 0; background: transparent; }
.record-list article { padding: 7px 0; border-left: 0; }
.phase { padding: 2px 5px; border-radius: 3px; }
:deep(.reference-card) { padding: 7px 0; }
:deep(.structured-card) { overflow: visible; }
:deep(.data-card__heading) { padding: 6px 0; }
:deep(.structured-card pre), pre { max-height: 160px; padding: 7px 0; }
@media (max-width: 760px) { .operational-inspector :deep(.el-tabs__item) { padding: 0 7px; } .tab-label .el-icon { display: none; } }
</style>
