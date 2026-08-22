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
        <OperationalGroup title="控制 Frame" :items="controlFrames" />
        <OperationalMap title="Loop 迭代" :value="view.operational?.loopIterations || {}" />
        <OperationalMap title="Consensus" :value="view.operational?.consensusResults || {}" />
        <OperationalMap title="Debate" :value="view.operational?.debateSessions || {}" />
      </el-tab-pane>

      <el-tab-pane name="context">
        <template #label><span class="tab-label"><el-icon><Connection /></el-icon>通信上下文</span></template>
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
        <AcgProvenancePanel
          :consumptions="view.provenance.consumptions"
          :interactions="view.interactions"
          :recovery-trace="view.recoveryTrace"
          :contract-violations="view.contractViolations"
          @export-json="emit('export-audit', 'json')"
          @export-csv="emit('export-audit', 'csv')"
        />
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
import AcgProvenancePanel from './AcgProvenancePanel.vue'
import RuntimeAuditTimeline from './RuntimeAuditTimeline.vue'

const props = defineProps<{ view: AcgView; auditEvents: TraceEvent[]; patchRefs: string[] }>()
const emit = defineEmits<{ 'export-audit': [format: 'json' | 'csv'] }>()
const activeTab = ref('runtime')
const records = computed(() => props.view.operational?.nodeExecutions || [])
const controlFrames = computed(() => props.view.operational?.controlFrames || [])

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
        ? h('div', { class: 'reference-list' }, componentProps.refs.map(item => h('code', { title: item }, item)))
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
        ? h('div', { class: 'json-list' }, componentProps.items.map((item, index) => h('pre', { key: index }, formatValue(item))))
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
        ? h('pre', formatValue(componentProps.value))
        : h('p', { class: 'empty' }, emptyText(componentProps.title))
    ])
  }
})
</script>

<style scoped>
.operational-inspector { min-width: 0; border-radius: 0; box-shadow: none; }
.operational-inspector :deep(.el-tabs__header) { margin: 0; padding: 0 8px; }
.operational-inspector :deep(.el-tabs__nav-wrap::after) { height: 1px; background: var(--border-light); }
.operational-inspector :deep(.el-tabs__content) { padding: 10px; overflow: visible; }
.tab-label { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; }
.section-block { display: grid; gap: 7px; padding: 10px 2px; border-bottom: 1px solid var(--border-light); }
.section-block header, .record-list article > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.section-block header strong { font-size: 12px; }
.section-block header span, .empty { color: var(--text-secondary); font-size: 10px; }
.empty { margin: 0; }
.record-list { display: grid; gap: 6px; }
.record-list article { display: grid; gap: 4px; padding: 8px; border-left: 2px solid var(--border-light); background: var(--bg-input); }
.record-list strong { overflow-wrap: anywhere; font-size: 11px; }
.record-list code, .record-list small { overflow-wrap: anywhere; color: var(--text-secondary); font-size: 9px; }
.record-list .failure { color: var(--danger); }
.phase { padding: 2px 5px; border-radius: 4px; color: var(--primary-color); background: var(--primary-fade); font-size: 9px; }
.phase.committed { color: var(--success); background: var(--success-fade); }
.phase.failed, .phase.cancelled { color: var(--danger); background: var(--danger-fade); }
.phase.waiting_review { color: var(--warning); background: var(--warning-fade); }
.reference-list { display: grid; gap: 5px; }
.reference-list code { padding: 6px; overflow-wrap: anywhere; border-radius: 4px; background: var(--bg-input); color: var(--text-secondary); font-size: 9px; }
pre { max-width: 100%; max-height: 220px; margin: 0; padding: 8px; overflow: auto; border-radius: 5px; background: var(--bg-input); color: var(--text-secondary); font: 9px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.operational-inspector :deep(.acg-metrics), .operational-inspector :deep(.acg-provenance), .operational-inspector :deep(.runtime-audit-timeline) { border: 0; border-radius: 0; box-shadow: none; }
@media (max-width: 760px) { .operational-inspector :deep(.el-tabs__item) { padding: 0 7px; } .tab-label .el-icon { display: none; } }
</style>
