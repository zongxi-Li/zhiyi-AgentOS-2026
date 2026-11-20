<script setup lang="ts">
import { inject } from 'vue'
import InspectorFrame from '@/components/workbench/InspectorFrame.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import { graphVersionTime, graphVersionsKey } from './graphVersions'

defineProps<{ fullscreen?: boolean }>()
const emit = defineEmits<{ close: []; toggleFullscreen: [] }>()
const versions = inject(graphVersionsKey, null)
</script>

<template>
  <InspectorFrame v-if="versions?.selected.value" :title="`图版本 v${versions.selected.value.graphVersion}`" historical
    :fullscreen="fullscreen" @close="emit('close')" @toggle-fullscreen="emit('toggleFullscreen')">
    <InspectorSection title="历史图快照" badge="只读">
      <p>{{ versions.selected.value.reason || (versions.previous.value ? '执行图修订' : '初始执行图') }}</p>
      <InspectorPropertyList :rows="[
        { label: '记录时间', value: graphVersionTime(versions.selected.value) },
        { label: '节点', value: versions.displayGraph.value?.nodes.length },
        { label: '依赖', value: versions.displayGraph.value?.edges.length }
      ]" />
      <p class="version-inspector-note">展示此版本保存的结构。当前执行状态请在运行进度或任务助手中查看。</p>
    </InspectorSection>
    <InspectorSection v-if="versions.selected.value.patch" title="本次结构修订">
      <InspectorPropertyList :rows="[
        { label: '新增节点', value: String(versions.selected.value.patch.addedNodeIds.length) },
        { label: '调整节点', value: String(versions.selected.value.patch.updatedNodeIds.length) },
        { label: '移除节点', value: String(versions.selected.value.patch.removedNodeIds.length) },
        { label: '依赖变化', value: `+${versions.selected.value.patch.addedEdgeCount} / −${versions.selected.value.patch.removedEdgeCount}` }
      ]" />
    </InspectorSection>
    <InspectorSection v-if="versions.selected.value.handoffId" title="交接时保留的证据">
      <InspectorPropertyList :rows="[
        { label: '已完成节点', value: String(versions.selected.value.inherited.completedStepIds.length) },
        { label: '结果引用', value: String(Object.keys(versions.selected.value.inherited.outputRefs).length) }
      ]" />
    </InspectorSection>
    <InspectorSection title="快照标识">
      <InspectorPropertyList :rows="[
        { label: 'Graph ID', value: versions.selected.value.graphId, code: true },
        { label: 'Blueprint ID', value: versions.selected.value.blueprintId, code: true }
      ]" />
    </InspectorSection>
  </InspectorFrame>
</template>

<style scoped>
.version-inspector-note { color: var(--wb-text-muted); font-size: 11px; }
</style>
