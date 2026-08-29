<template>
  <div class="sidebar-view-stack">
    <InspectorSection title="通信摘要" :badge="items.length ? `${items.length} records` : '未观测'">
      <div class="sidebar-metrics" aria-label="通信统计">
        <div><strong>{{ inboundCount }}</strong><span>Inbound</span></div>
        <div><strong>{{ outboundCount }}</strong><span>Outbound</span></div>
        <div><strong>{{ provenanceCount }}</strong><span>Provenance</span></div>
      </div>
      <InspectorPropertyList :rows="[
        { label: '当前对象', value: objectLabel },
        { label: '字段观测', value: observedFieldCount },
        { label: 'Artifact refs', value: artifactRefCount },
        { label: 'source', value: items.length ? 'provenance / trace' : '未观测' }
      ]" />
      <p v-if="!runtimeObservation" class="sidebar-empty">未观测到通信数据。</p>
      <p v-else-if="!relatedItems.length" class="sidebar-empty">当前对象没有可证明的相关通信。</p>
    </InspectorSection>

    <InspectorSection v-if="relatedItems.length" title="最近相关通信" badge="只读摘要">
      <div class="communication-list">
        <div v-for="item in relatedItems" :key="item.id" class="communication-list__item">
          <strong>{{ item.summary }}</strong>
          <span>{{ item.source }} · {{ formatDate(item.timestamp) }}</span>
          <small>{{ item.artifactRef || (item.fields.length ? item.fields.join(', ') : 'evidence 未观测') }}</small>
        </div>
      </div>
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

const items = computed(() => props.runtimeObservation?.communication || [])
const objectLabel = computed(() => props.context.graphNode?.name || props.context.entry?.name || 'Mission')
const targetIds = computed(() => new Set([
  props.context.selectedAcgNodeId,
  props.context.graphNode?.acgNodeId,
  props.context.graphNode?.taskId,
  props.context.entry?.acgNodeId,
  props.context.entry?.taskId
].filter((value): value is string => Boolean(value))))
const relatedItems = computed(() => {
  const entry = props.context.entry
  const targets = targetIds.value
  const artifactRefs = new Set([entry?.artifactId, entry?.contentRef].filter((value): value is string => Boolean(value)))
  const related = items.value.filter(item => (
    targets.has(item.producerStepId || '')
    || targets.has(item.consumerStepId || '')
    || Boolean(item.artifactRef && artifactRefs.has(item.artifactRef))
  ))
  const source = related.length || targets.size || artifactRefs.size ? related : items.value
  return source.slice(-3).reverse()
})
const inboundCount = computed(() => {
  const targets = targetIds.value
  return targets.size ? items.value.filter(item => targets.has(item.consumerStepId || '')).length : 0
})
const outboundCount = computed(() => {
  const targets = targetIds.value
  return targets.size ? items.value.filter(item => targets.has(item.producerStepId || '')).length : 0
})
const provenanceCount = computed(() => items.value.filter(item => item.source === 'provenance').length)
const observedFieldCount = computed(() => new Set(items.value.flatMap(item => item.fields)).size)
const artifactRefCount = computed(() => new Set(items.value.map(item => item.artifactRef).filter(Boolean)).size)
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '时间未观测'
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.sidebar-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 8px; }
.sidebar-metrics > div { display: grid; gap: 2px; min-width: 0; }
.sidebar-metrics strong { color: var(--wb-text); font: 16px var(--font-mono, monospace); }
.sidebar-metrics span { color: var(--wb-text-muted); font-size: 10px; }
.communication-list { display: grid; gap: 10px; }
.communication-list__item { display: grid; gap: 3px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.communication-list__item:first-child { padding-top: 0; border-top: 0; }
.communication-list__item strong { overflow: hidden; color: var(--wb-text); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.communication-list__item span, .communication-list__item small { overflow: hidden; color: var(--wb-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-empty { margin: 10px 0 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1.5; }
</style>
