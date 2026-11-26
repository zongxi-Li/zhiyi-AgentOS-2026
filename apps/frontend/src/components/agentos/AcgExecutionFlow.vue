<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { MarkerType, VueFlow, useVueFlow, type Node } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import AcgExecutionNode from './AcgExecutionNode.vue'
import type { GraphProjection } from '@/services/api/agentos'
import type { GraphDifference } from '@/utils/acgGraphDifference'
import { graphChangeColor, graphChangeLabel, graphDifferenceMaps } from '@/utils/acgGraphDifference'

const props = defineProps<{
  blueprint: GraphProjection
  positions: Map<string, { x: number; y: number }>
  selectedId: string
  anchorId: string
  statuses: Record<string, { status: string; label: string }>
  difference?: GraphDifference | null
  historical?: boolean
  overviewOnLoad?: boolean
}>()
const emit = defineEmits<{ select: [id: string]; doubleClick: [id: string]; zoom: [percent: number] }>()
const flow = useVueFlow()
const nodes = shallowRef<Node[]>([])
const expandedId = ref(props.selectedId)
const sizes = new Map<string, { width: number; height: number }>()
const draggedCenters = new Map<string, { x: number; y: number }>()
const changes = computed(() => graphDifferenceMaps(props.difference))
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
    const change = changes.value.nodes.get(node.nodeId)
    const status = props.historical || change === 'removed' ? { status: 'snapshot', label: '快照' }
      : props.statuses[node.nodeId] || { status: 'pending', label: '待执行' }
    const label = change ? `${graphChangeLabel[change]} · ${status.label}` : status.label
    return {
      id: node.nodeId, type: 'execution',
      position: { x: center.x - size.width / 2, y: center.y + shift - size.height / 2 },
      data: { name: node.name || node.nodeId, ...status, label },
      class: change ? `difference-${change}` : '',
      connectable: false, selectable: false, zIndex: node.nodeId === props.selectedId ? 10 : 0,
      ariaLabel: `${node.name || node.nodeId} · ${label}`
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
  const change = changes.value.edges.get(edge.edgeId)
  const stroke = change ? graphChangeColor[change] : 'var(--wb-text-secondary, #8590a3)'
  return {
    id: edge.edgeId || `execution-edge-${index}`, source: edge.sourceId, target: edge.targetId,
    type: 'default', markerEnd: MarkerType.ArrowClosed,
    style: { stroke, strokeWidth: change ? 2 : emphasized ? 1.5 : 1, opacity: change ? 0.95 : emphasized ? 0.8 : 0.16,
      ...(change === 'removed' ? { strokeDasharray: '6 5' } : {}) },
    label: change ? graphChangeLabel[change] : undefined,
    class: [change ? `difference-${change}` : '', !props.historical && edge.activation === 'inactive' ? 'is-inactive' : ''].filter(Boolean).join(' ')
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
let focusRequest: { id: string; sequence: number } | null = null
let cameraSequence = 0
let disposed = false
const actualSize = async (id = props.selectedId || props.anchorId, duration = 240) => {
  const sequence = ++cameraSequence
  focusRequest = { id, sequence }
  await nextTick()
  if (disposed || sequence !== cameraSequence) return
  if (!props.blueprint.nodes.some(node => node.nodeId === id)) { focusRequest = null; return }
  if (flow.dimensions.value.width <= 0 || flow.dimensions.value.height <= 0) return
  const center = centerOf(id)
  const centered = await flow.setCenter(center.x, center.y, { zoom: 1, duration })
  if (sequence === cameraSequence && centered !== false) focusRequest = null
}
const cancelFocus = () => { cameraSequence++; focusRequest = null }
const overview = () => {
  cancelFocus()
  return flow.fitView({ padding: 0.15, duration: 300, minZoom: 0.08, maxZoom: 1 })
}
const initialView = async () => {
  await nextTick()
  if (disposed) return
  if (!props.overviewOnLoad) return actualSize(props.anchorId, 0)
  const { width, height } = flow.dimensions.value
  if (width <= 0 || height <= 0 || !nodes.value.length) return
  // Planning nodes have deterministic layout bounds before DOM measurement.
  const bounds = nodes.value.map(node => ({ ...node.position, ...(sizes.get(node.id) || closedSize) }))
  const left = Math.min(...bounds.map(node => node.x)), top = Math.min(...bounds.map(node => node.y))
  const right = Math.max(...bounds.map(node => node.x + node.width)), bottom = Math.max(...bounds.map(node => node.y + node.height))
  const zoom = Math.min(1, Math.max(0.08, Math.min(width / (right - left + 80), height / (bottom - top + 80))))
  cancelFocus()
  return flow.setViewport({ x: width / 2 - (left + right) / 2 * zoom,
    y: height / 2 - (top + bottom) / 2 * zoom, zoom }, { duration: 0 })
}
let overviewVersion = ''
const onNodesInitialized = () => {
  if (!props.overviewOnLoad) return
  const version = JSON.stringify([props.blueprint.graphId, props.blueprint.graphVersion])
  if (overviewVersion === version) return
  overviewVersion = version
  void initialView()
}
const zoomBy = (factor: number) => {
  cancelFocus()
  return flow.zoomTo(Math.max(0.08, Math.min(2.4, flow.viewport.value.zoom * factor)), { duration: 180 })
}
watch([() => props.blueprint.graphId, () => props.blueprint.graphVersion], () => {
  sizes.clear(); draggedCenters.clear(); expandedId.value = ''; placeNodes()
  void initialView()
})
watch(() => props.selectedId, id => { expandedId.value = id; placeNodes() })
watch(() => [props.blueprint, props.positions, props.statuses, props.difference, props.historical], placeNodes, { immediate: true, deep: true })
watch(() => props.anchorId, id => {
  // Explicit node selection owns its own camera request. Execution advancing
  // without a selection follows the new active node once, not on every poll.
  if (!props.selectedId && !props.overviewOnLoad) void actualSize(id)
})
watch(() => [flow.dimensions.value.width, flow.dimensions.value.height], ([width, height], [oldWidth, oldHeight]) => {
  if (width <= 0 || height <= 0) return
  if (focusRequest || oldWidth <= 0 || oldHeight <= 0) {
    if (props.overviewOnLoad && !focusRequest && !props.selectedId) void initialView()
    else void actualSize(focusRequest?.id || props.selectedId || props.anchorId, 0)
    return
  }
  // Pane resizing and review/header expansion change the visible canvas.
  // Keep its world-space center and the user's zoom, including after panning.
  const viewport = flow.viewport.value
  void flow.setViewport({ x: viewport.x + (width - oldWidth) / 2,
    y: viewport.y + (height - oldHeight) / 2, zoom: viewport.zoom }, { duration: 0 })
}, { flush: 'post' })
flow.onInit(() => { void initialView() })
flow.onMoveStart(({ event }) => { if (event) cancelFocus() })
flow.onViewportChange(viewport => emit('zoom', Math.round(viewport.zoom * 100)))
flow.onNodeDragStop(({ node }) => {
  cancelFocus()
  const size = sizes.get(node.id) || closedSize
  const previous = centerOf(node.id)
  const selected = centerOf(props.selectedId)
  const extraHalf = Math.max(0, ((sizes.get(props.selectedId)?.height || 44) - 44) / 2)
  const shift = node.id !== props.selectedId && Math.abs(previous.x - selected.x) < 1
    ? Math.sign(previous.y - selected.y) * extraHalf : 0
  draggedCenters.set(node.id, { x: node.position.x + size.width / 2, y: node.position.y + size.height / 2 - shift })
})
onBeforeUnmount(() => { disposed = true; cameraSequence++; focusRequest = null; sizes.clear(); draggedCenters.clear() })
defineExpose({ actualSize, overview, zoomBy, close })
</script>

<template>
  <VueFlow v-model:nodes="nodes" :edges="edges" :min-zoom="0.08" :max-zoom="2.4" :nodes-connectable="false"
    :delete-key-code="null" :selection-key-code="null" :zoom-on-double-click="false"
    @nodes-initialized="onNodesInitialized"
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
:deep(.vue-flow__node.difference-added .execution-node) { border-color: var(--sem-success, #8bcb78); box-shadow: 0 0 0 2px color-mix(in srgb, var(--sem-success, #8bcb78) 15%, transparent); }
:deep(.vue-flow__node.difference-updated .execution-node) { border-color: var(--sem-waiting, #d9b86c); box-shadow: 0 0 0 2px color-mix(in srgb, var(--sem-waiting, #d9b86c) 15%, transparent); }
:deep(.vue-flow__node.difference-removed .execution-node) { border-color: var(--sem-failed, #e06c75); border-style: dashed; background: color-mix(in srgb, var(--sem-failed, #e06c75) 7%, var(--wb-surface-2, #e6edf2)); }
</style>
