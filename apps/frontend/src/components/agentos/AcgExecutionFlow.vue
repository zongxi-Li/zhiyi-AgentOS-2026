<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { MarkerType, VueFlow, useVueFlow, type Node } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import AcgExecutionNode from './AcgExecutionNode.vue'
import type { GraphProjection } from '@/services/api/agentos'

const props = defineProps<{
  blueprint: GraphProjection
  positions: Map<string, { x: number; y: number }>
  selectedId: string
  anchorId: string
  statuses: Record<string, { status: string; label: string }>
}>()
const emit = defineEmits<{ select: [id: string]; doubleClick: [id: string]; zoom: [percent: number] }>()
const flow = useVueFlow()
const nodes = shallowRef<Node[]>([])
const expandedId = ref(props.selectedId)
const sizes = new Map<string, { width: number; height: number }>()
const draggedCenters = new Map<string, { x: number; y: number }>()
const centerOf = (id: string) => draggedCenters.get(id) || props.positions.get(id) || { x: 0, y: 0 }
const closedSize = { width: 320, height: 44 }
const placeNodes = () => {
  const expandedCenter = centerOf(props.selectedId)
  const expandedSize = sizes.get(props.selectedId) || closedSize
  const extraHalf = Math.max(0, (expandedSize.height - 44) / 2)
  nodes.value = props.blueprint.nodes.map(node => {
    const center = centerOf(node.nodeId)
    const size = sizes.get(node.nodeId) || closedSize
    const sameColumn = node.nodeId !== props.selectedId && Math.abs(center.x - expandedCenter.x) < 1
    const shift = sameColumn ? Math.sign(center.y - expandedCenter.y) * extraHalf : 0
    return {
      id: node.nodeId, type: 'execution',
      position: { x: center.x - size.width / 2, y: center.y + shift - size.height / 2 },
      data: { name: node.name || node.nodeId, ...(props.statuses[node.nodeId] || { status: 'pending', label: '待执行' }) },
      connectable: false, selectable: false, zIndex: node.nodeId === props.selectedId ? 10 : 0,
      ariaLabel: node.name || node.nodeId
    }
  })
}
const onDimensions = (id: string, size: { width: number; height: number }) => {
  const previous = sizes.get(id)
  if (previous && Math.abs(previous.width - size.width) < 0.01 && Math.abs(previous.height - size.height) < 0.01) return
  sizes.set(id, size)
  placeNodes()
}
const edges = computed(() => props.blueprint.edges.map((edge, index) => {
  const emphasized = !props.selectedId || edge.sourceId === props.selectedId || edge.targetId === props.selectedId
  return {
    id: edge.edgeId || `execution-edge-${index}`, source: edge.sourceId, target: edge.targetId,
    type: 'default', markerEnd: MarkerType.ArrowClosed,
    style: { stroke: 'var(--wb-text-secondary, #8590a3)', strokeWidth: emphasized ? 1.5 : 1, opacity: emphasized ? 0.8 : 0.16 },
    class: edge.activation === 'inactive' ? 'is-inactive' : ''
  }
}))
const close = () => { expandedId.value = '' }
const toggle = (id: string) => {
  if (expandedId.value === id) close()
  else { expandedId.value = id; emit('select', id) }
}
const collapsed = (id: string) => {
  if (props.selectedId === id && !expandedId.value) emit('select', '')
}
const actualSize = async (id = props.selectedId || props.anchorId, duration = 240) => {
  await nextTick()
  const center = centerOf(id)
  await flow.setCenter(center.x, center.y, { zoom: 1, duration })
}
const overview = () => flow.fitView({ padding: 0.15, duration: 300, minZoom: 0.08, maxZoom: 1 })
const zoomBy = (factor: number) => flow.zoomTo(Math.max(0.08, Math.min(2.4, flow.viewport.value.zoom * factor)), { duration: 180 })
watch(() => props.blueprint.graphId, () => { sizes.clear(); draggedCenters.clear(); placeNodes() })
watch(() => props.selectedId, id => { expandedId.value = id; placeNodes() })
watch(() => [props.blueprint, props.positions, props.statuses], placeNodes, { immediate: true, deep: true })
flow.onInit(() => { void actualSize(props.anchorId, 0) })
flow.onViewportChange(viewport => emit('zoom', Math.round(viewport.zoom * 100)))
flow.onNodeDragStop(({ node }) => {
  const size = sizes.get(node.id) || closedSize
  const previous = centerOf(node.id)
  const selected = centerOf(props.selectedId)
  const extraHalf = Math.max(0, ((sizes.get(props.selectedId)?.height || 44) - 44) / 2)
  const shift = node.id !== props.selectedId && Math.abs(previous.x - selected.x) < 1
    ? Math.sign(previous.y - selected.y) * extraHalf : 0
  draggedCenters.set(node.id, { x: node.position.x + size.width / 2, y: node.position.y + size.height / 2 - shift })
})
onBeforeUnmount(() => { sizes.clear(); draggedCenters.clear() })
defineExpose({ actualSize, overview, zoomBy, close })
</script>

<template>
  <VueFlow v-model:nodes="nodes" :edges="edges" :min-zoom="0.08" :max-zoom="2.4" :nodes-connectable="false"
    :delete-key-code="null" :selection-key-code="null" :zoom-on-double-click="false"
    @node-double-click="emit('doubleClick', $event.node.id)" @pane-click="close">
    <template #node-execution="{ id, data }">
      <AcgExecutionNode :id="id" :name="data.name" :status="data.status" :status-label="data.label"
        :expanded="expandedId === id" :has-detail="selectedId === id" @toggle="toggle(id)"
        @dimensions="onDimensions(id, $event)" @collapsed="collapsed(id)">
        <slot v-if="selectedId === id" name="detail" />
      </AcgExecutionNode>
    </template>
  </VueFlow>
</template>

<style scoped>
:deep(.vue-flow__node-execution) { border: 0; padding: 0; background: transparent; }
:deep(.vue-flow__edge.is-inactive path) { stroke-dasharray: 6 5; }
:deep(.vue-flow__edge-path) { transition: opacity 160ms ease; }
</style>
