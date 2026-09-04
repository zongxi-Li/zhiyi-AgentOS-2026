<template>
  <div class="sidebar-view-stack">
    <InspectorSection v-if="hasStepSnapshot" title="步骤上下文" badge="projection">
      <InspectorPropertyList :rows="[
        { label: 'objective', value: context.entry?.objective },
        { label: 'dependencies', value: dependencyKeys.length }
      ]" />
      <div v-if="dependencyKeys.length" class="dependency-list">
        <code v-for="dependency in dependencyKeys" :key="dependency">{{ dependency }}</code>
      </div>
    </InspectorSection>

    <InspectorSection title="控制协同" :badge="operational ? `${controlRecordCount} records` : '未观测'">
      <div v-if="operational" class="sidebar-metrics" aria-label="控制协同统计">
        <div><strong>{{ operational.controlFrames.length }}</strong><span>Control Frame</span></div>
        <div><strong>{{ Object.keys(operational.loopIterations).length }}</strong><span>Loop</span></div>
        <div><strong>{{ Object.keys(operational.consensusResults).length }}</strong><span>Consensus</span></div>
        <div><strong>{{ Object.keys(operational.debateSessions).length }}</strong><span>Debate</span></div>
      </div>
      <p v-if="!operational" class="sidebar-empty">未观测到控制协同数据。</p>
      <template v-else>
        <OperationalRecords title="控制 Frame" :items="operational.controlFrames" />
        <OperationalMap title="Loop 迭代" :value="operational.loopIterations" />
        <OperationalMap title="Consensus" :value="operational.consensusResults" />
        <OperationalMap title="Debate" :value="operational.debateSessions" />
      </template>
    </InspectorSection>

    <InspectorSection title="通信上下文" :badge="operational ? `${contextReferenceCount} refs` : '未观测'">
      <p v-if="!operational" class="sidebar-empty">未观测到通信上下文数据。</p>
      <template v-else>
        <ReferenceGroup title="Communication" :items="operational.communicationRefs" />
        <ReferenceGroup title="Memory" :items="operational.memoryRefs" />
        <ReferenceGroup title="Evidence" :items="operational.evidenceRefs" />
        <OperationalMap title="Lease" :value="operational.leaseStatuses" />
      </template>
    </InspectorSection>

    <InspectorSection title="上下文数据" badge="未观测">
      <p class="sidebar-empty">未观测到 Context Pack、Memory 或 token context。</p>
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, type PropType } from 'vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import type { WorkbenchInspectorContext } from '@/workbench/types'

const props = defineProps<{
  context: WorkbenchInspectorContext
  runtimeObservation: RuntimeObservation | null
}>()
const dependencyKeys = computed(() => props.context.entry?.dependencyKeys || [])
const hasStepSnapshot = computed(() => Boolean(props.context.entry?.objective || dependencyKeys.value.length))
const operational = computed(() => props.runtimeObservation?.operational || null)
const controlRecordCount = computed(() => {
  const value = operational.value
  return value
    ? value.controlFrames.length
      + Object.keys(value.loopIterations).length
      + Object.keys(value.consensusResults).length
      + Object.keys(value.debateSessions).length
    : 0
})
const contextReferenceCount = computed(() => {
  const value = operational.value
  return value
    ? value.communicationRefs.length
      + value.memoryRefs.length
      + value.evidenceRefs.length
      + Object.keys(value.leaseStatuses).length
    : 0
})

const formatValue = (value: unknown) => {
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

const renderStructuredValue = (value: unknown) => {
  if (!value || typeof value !== 'object') {
    return h('span', { class: 'structured-value' }, String(value ?? '未观测'))
  }
  const entries = Object.entries(value as Record<string, unknown>)
  if (!entries.length) return h('span', { class: 'structured-value' }, '空对象')
  return h('div', { class: 'structured-fields' }, [
    ...entries.map(([key, item]) => h('div', { class: 'structured-field', key }, [
      h('span', { class: 'structured-field__label' }, key),
      renderFieldValue(item)
    ])),
    h('details', { class: 'structured-raw' }, [
      h('summary', '展开原始数据'),
      h('pre', formatValue(value))
    ])
  ])
}

const renderFieldValue = (value: unknown) => {
  if (value && typeof value === 'object') {
    return h('details', { class: 'structured-field__nested' }, [
      h('summary', Array.isArray(value) ? `${value.length} 项` : '展开'),
      h('pre', formatValue(value))
    ])
  }
  return h('strong', { class: 'structured-field__value' }, String(value ?? '未观测'))
}

const ReferenceGroup = defineComponent({
  props: {
    title: { type: String, required: true },
    items: { type: Array as PropType<string[]>, required: true }
  },
  setup(componentProps) {
    return () => h('div', { class: 'context-record-group' }, [
      h('div', { class: 'context-record-group__heading' }, [
        h('strong', componentProps.title),
        h('span', String(componentProps.items.length))
      ]),
      componentProps.items.length
        ? h('div', { class: 'reference-list' }, componentProps.items.map((item, index) => h('code', {
          class: 'reference-item',
          key: `${item}:${index}`,
          title: item
        }, item)))
        : h('p', { class: 'sidebar-empty' }, `暂无 ${componentProps.title} 引用。`)
    ])
  }
})

const OperationalRecords = defineComponent({
  props: {
    title: { type: String, required: true },
    items: { type: Array as PropType<Array<Record<string, unknown>>>, required: true }
  },
  setup(componentProps) {
    return () => h('div', { class: 'context-record-group' }, [
      h('div', { class: 'context-record-group__heading' }, [
        h('strong', componentProps.title),
        h('span', String(componentProps.items.length))
      ]),
      componentProps.items.length
        ? h('div', { class: 'structured-list' }, componentProps.items.map((item, index) => h('article', {
          class: 'structured-record',
          key: index
        }, [
          h('strong', `记录 ${String(index + 1).padStart(2, '0')}`),
          renderStructuredValue(item)
        ])))
        : h('p', { class: 'sidebar-empty' }, `暂无 ${componentProps.title} 数据。`)
    ])
  }
})

const OperationalMap = defineComponent({
  props: {
    title: { type: String, required: true },
    value: { type: Object as PropType<Record<string, unknown>>, required: true }
  },
  setup(componentProps) {
    return () => h('div', { class: 'context-record-group' }, [
      h('div', { class: 'context-record-group__heading' }, [
        h('strong', componentProps.title),
        h('span', String(Object.keys(componentProps.value).length))
      ]),
      Object.keys(componentProps.value).length
        ? h('div', { class: 'structured-list' }, Object.entries(componentProps.value).map(([key, value]) => h('article', {
          class: 'structured-record',
          key
        }, [
          h('code', { title: key }, key),
          renderStructuredValue(value)
        ])))
        : h('p', { class: 'sidebar-empty' }, `暂无 ${componentProps.title} 数据。`)
    ])
  }
})
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.dependency-list { display: grid; gap: 5px; margin-top: 10px; }
.dependency-list code { overflow-wrap: anywhere; color: var(--wb-text); font: 10px/1.4 var(--font-mono, monospace); }
.sidebar-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 10px; }
.sidebar-metrics > div { display: grid; gap: 2px; min-width: 0; }
.sidebar-metrics strong { color: var(--wb-text); font: 15px var(--font-mono, monospace); }
.sidebar-metrics span { color: var(--wb-text-muted); font-size: 9px; line-height: 1.3; }
:deep(.context-record-group) { display: grid; gap: 8px; margin-top: 12px; }
:deep(.context-record-group:first-child) { margin-top: 0; }
:deep(.context-record-group__heading) { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; }
:deep(.context-record-group__heading strong) { min-width: 0; overflow-wrap: anywhere; color: var(--wb-text-secondary); font-size: 10px; font-weight: 650; letter-spacing: .01em; }
:deep(.context-record-group__heading span) { flex: 0 0 auto; padding: 2px 5px; border-radius: 4px; color: var(--wb-accent); background: var(--wb-accent-soft); font: 9px var(--font-mono, monospace); }
:deep(.reference-list), :deep(.structured-list) { display: grid; gap: 6px; }
:deep(.reference-item) { display: block; min-width: 0; overflow-wrap: anywhere; padding: 7px 9px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: 9px/1.4 var(--font-mono, monospace); }
:deep(.reference-item:hover) { border-color: color-mix(in srgb, var(--wb-accent) 24%, var(--wb-border-soft)); background: var(--wb-hover); }
:deep(.structured-record) { display: grid; gap: 8px; min-width: 0; padding: 10px 11px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-md); background: color-mix(in srgb, var(--wb-surface-inset) 68%, var(--wb-surface-section)); box-shadow: 0 1px 2px color-mix(in srgb, var(--wb-text) 3%, transparent); }
:deep(.structured-record > strong), :deep(.structured-record > code) { overflow-wrap: anywhere; color: var(--wb-text-secondary); font: 10px/1.4 var(--font-mono, monospace); }
:deep(.structured-record > strong) { color: var(--wb-text); font-weight: 650; }
:deep(.structured-fields) { display: grid; gap: 0; min-width: 0; overflow: hidden; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); background: color-mix(in srgb, var(--wb-surface-section) 72%, transparent); }
:deep(.structured-field) { display: grid; grid-template-columns: minmax(118px, .85fr) minmax(0, 1.15fr); align-items: baseline; gap: 14px; min-width: 0; padding: 7px 9px; border-bottom: 1px solid var(--wb-border-soft); }
:deep(.structured-field:last-of-type) { border-bottom: 0; }
:deep(.structured-field__label) { min-width: 0; overflow-wrap: anywhere; color: var(--wb-text-muted); font: 9px/1.35 var(--font-mono, monospace); }
:deep(.structured-field__value) { min-width: 0; overflow-wrap: anywhere; color: var(--wb-text); font: 10px/1.35 var(--font-mono, monospace); text-align: right; }
:deep(.structured-field__nested) { min-width: 0; color: var(--wb-accent); font: 9px/1.35 var(--font-mono, monospace); text-align: right; }
:deep(.structured-field__nested) summary, :deep(.structured-raw) summary { cursor: pointer; }
:deep(.structured-field__nested) summary:hover, :deep(.structured-raw) summary:hover { color: var(--wb-text); }
:deep(.structured-field__nested) pre, :deep(.structured-raw) pre { max-height: 180px; margin: 5px 0 0; overflow: auto; color: var(--wb-text-muted); font: 9px/1.5 var(--font-mono, monospace); text-align: left; white-space: pre-wrap; overflow-wrap: anywhere; }
:deep(.structured-raw) { padding: 7px 9px; color: var(--wb-text-muted); font-size: 9px; }
:deep(.structured-value) { min-width: 0; overflow-wrap: anywhere; color: var(--wb-text); font: 10px/1.35 var(--font-mono, monospace); }
:deep(.sidebar-empty) { margin: 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1.6; }
@media (max-width: 480px) { .sidebar-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
