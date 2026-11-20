import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AcgExecutionFlow from './AcgExecutionFlow.vue'

const { api } = vi.hoisted(() => ({ api: {
  setCenter: vi.fn(), setViewport: vi.fn(), fitView: vi.fn(), zoomTo: vi.fn(),
  dimensions: { value: { width: 800, height: 600 } },
  viewport: { value: { x: 0, y: 0, zoom: 0.5 } },
  onInit: vi.fn(), onMoveStart: vi.fn(), onViewportChange: vi.fn(), onNodeDragStop: vi.fn()
} }))
vi.mock('@vue-flow/core', async () => {
  const { defineComponent, h, shallowRef } = await import('vue')
  api.dimensions = shallowRef(api.dimensions.value)
  api.viewport = shallowRef(api.viewport.value)
  return {
    MarkerType: { ArrowClosed: 'arrowclosed' }, useVueFlow: () => api,
    VueFlow: defineComponent({
      name: 'VueFlow',
      props: ['nodes', 'edges'],
      setup(props, { slots }) {
        return () => h('div', props.nodes.map((node: any) => slots['node-execution']?.({ id: node.id, data: node.data })))
      }
    })
  }
})
vi.mock('./AcgExecutionNode.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({
    name: 'AcgExecutionNode',
    props: ['id', 'name', 'status', 'statusLabel', 'expanded', 'hasDetail'],
    emits: ['dimensions', 'toggle', 'collapsed'],
    setup: props => () => h('button', { 'data-node': props.id }, props.name)
  }) }
})
const positions = new Map([['a', { x: 0, y: -160 }], ['b', { x: 0, y: 0 }], ['c', { x: 0, y: 160 }]])
const blueprint = {
  graphId: 'flow-test', nodes: ['a', 'b', 'c'].map(nodeId => ({ nodeId, nodeType: 'step' as const, name: nodeId })),
  edges: [{ edgeId: 'ab', sourceId: 'a', targetId: 'b', edgeType: 'dependency' as const }]
}
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  api.dimensions.value = { width: 800, height: 600 }
  api.viewport.value = { x: 0, y: 0, zoom: 0.5 }
  api.setCenter.mockResolvedValue(true)
  api.setViewport.mockImplementation(viewport => { api.viewport.value = viewport; return Promise.resolve(true) })
})
const setup = () => {
  const wrapper = mount(AcgExecutionFlow, { props: { blueprint, positions, selectedId: 'b', anchorId: 'b', statuses: {} } })
  wrappers.push(wrapper)
  return wrapper
}
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks() })
const flow = (w: ReturnType<typeof mount>) => w.findComponent({ name: 'VueFlow' })
const nodeRows = (w: ReturnType<typeof mount>) => flow(w).props('nodes') as any[]

describe('execution flow geometry', () => {
  it('keeps the expanding center fixed and opens space above and below in the same frame', async () => {
    const wrapper = setup()
    const node = wrapper.findAllComponents({ name: 'AcgExecutionNode' }).find(n => n.props('id') === 'b')!
    node.vm.$emit('dimensions', { width: 380, height: 400 })
    await flushPromises()
    const rows = nodeRows(wrapper)
    const expanded = rows.find(n => n.id === 'b')!
    expect(expanded.position).toEqual({ x: -190, y: -200 })
    expect(rows.find(n => n.id === 'a')!.position.y + 22).toBe(-338)
    expect(rows.find(n => n.id === 'c')!.position.y + 22).toBe(338)
    node.vm.$emit('dimensions', { width: 320, height: 44 })
    await flushPromises()
    expect(nodeRows(wrapper).find(n => n.id === 'a')!.position.y + 22).toBe(-160)
    expect(nodeRows(wrapper).find(n => n.id === 'c')!.position.y + 22).toBe(160)
  })
  it('preserves curved directed edges through every size update', async () => {
    const wrapper = setup()
    expect(flow(wrapper).props('edges')[0]).toMatchObject({ source: 'a', target: 'b', type: 'default', markerEnd: 'arrowclosed' })
  })
  it('never creates layout-only nodes outside the visible blueprint', async () => {
    const wrapper = setup()
    await wrapper.setProps({ blueprint: { ...blueprint, nodes: blueprint.nodes.slice(0, 2) } })
    expect(nodeRows(wrapper).map(n => n.id)).toEqual(['a', 'b'])
  })
  it('renders supplemental read and review nodes only after the formal graph changes', async () => {
    const wrapper = setup()
    expect(nodeRows(wrapper).map(node => node.id)).toEqual(['a', 'b', 'c'])
    const revised = { ...blueprint, graphVersion: 2,
      nodes: [...blueprint.nodes, { nodeId: 'supplement', nodeType: 'step' as const, name: '补读剩余文件' },
        { nodeId: 'review', nodeType: 'step' as const, name: '复核仓库证据' }],
      edges: [...blueprint.edges, { edgeId: 'read-review', sourceId: 'supplement', targetId: 'review', edgeType: 'dependency' as const }],
    }
    await wrapper.setProps({ blueprint: revised })
    expect(nodeRows(wrapper).map(node => node.id)).toEqual(revised.nodes.map(node => node.nodeId))
    expect(flow(wrapper).props('edges').map((edge: any) => [edge.source, edge.target]))
      .toEqual(revised.edges.map(edge => [edge.sourceId, edge.targetId]))
  })
  it('does not move the camera on runtime status changes and uses flow viewport controls', async () => {
    const wrapper = setup()
    await wrapper.setProps({ statuses: { b: { status: 'completed', label: 'Completed' } } })
    expect(api.setCenter).not.toHaveBeenCalled()
    await wrapper.vm.actualSize('b', 0)
    expect(api.setCenter).toHaveBeenCalledWith(0, 0, { zoom: 1, duration: 0 })
    wrapper.vm.zoomBy(2)
    expect(api.zoomTo).toHaveBeenCalledWith(1, { duration: 180 })
  })
  it('follows a changed execution anchor while leaving explicit selections in control', async () => {
    const wrapper = setup()
    await wrapper.setProps({ selectedId: '', anchorId: 'c' })
    await flushPromises()
    expect(api.setCenter).toHaveBeenLastCalledWith(0, 160, { zoom: 1, duration: 240 })
    api.setCenter.mockClear()
    await wrapper.setProps({ selectedId: 'a', anchorId: 'a' })
    await flushPromises()
    expect(api.setCenter).not.toHaveBeenCalled()
  })
  it('keeps the same world center and zoom when panels change the canvas size', async () => {
    setup()
    // A user has panned and zoomed: the world center is (300, 50).
    api.viewport.value = { x: -200, y: 200, zoom: 2 }
    api.dimensions.value = { width: 600, height: 400 }
    await flushPromises()
    expect(api.setViewport).toHaveBeenLastCalledWith({ x: -300, y: 100, zoom: 2 }, { duration: 0 })
    api.dimensions.value = { width: 900, height: 700 }
    await flushPromises()
    expect(api.setViewport).toHaveBeenLastCalledWith({ x: -150, y: 250, zoom: 2 }, { duration: 0 })
    expect(api.setCenter).not.toHaveBeenCalled()
  })
  it('defers focusing a hidden canvas until its dimensions become usable', async () => {
    api.dimensions.value = { width: 0, height: 0 }
    const wrapper = setup()
    await wrapper.vm.actualSize('c', 0)
    expect(api.setCenter).not.toHaveBeenCalled()
    api.dimensions.value = { width: 600, height: 400 }
    await flushPromises()
    expect(api.setCenter).toHaveBeenLastCalledWith(0, 160, { zoom: 1, duration: 0 })
    expect(api.setViewport).not.toHaveBeenCalled()
  })
  it('preserves user panning that interrupts a focus animation when the canvas resizes', async () => {
    let finishCenter!: (centered: boolean) => void
    api.setCenter.mockImplementation(() => new Promise<boolean>(resolve => { finishCenter = resolve }))
    const wrapper = setup()
    const focusing = wrapper.vm.actualSize('c')
    await flushPromises()
    api.onMoveStart.mock.calls[0][0]({ event: new Event('pointerdown') })
    api.viewport.value = { x: 100, y: 80, zoom: 0.8 }
    api.dimensions.value = { width: 1000, height: 400 }
    await flushPromises()
    expect(api.setCenter).toHaveBeenCalledTimes(1)
    expect(api.setViewport).toHaveBeenLastCalledWith({ x: 200, y: -20, zoom: 0.8 }, { duration: 0 })
    finishCenter(true)
    await focusing
  })
  it('marks added, changed and removed structure while historical nodes stay snapshots', async () => {
    const wrapper = setup()
    await wrapper.setProps({ historical: true, statuses: { a: { status: 'running', label: '运行中' } },
      blueprint: { ...blueprint, edges: [...blueprint.edges,
        { edgeId: 'bc', sourceId: 'b', targetId: 'c', edgeType: 'dependency' as const },
        { edgeId: 'ac', sourceId: 'a', targetId: 'c', edgeType: 'dependency' as const }] },
      difference: { addedNodeIds: ['a'], updatedNodeIds: ['b'], removedNodeIds: ['c'],
        addedEdgeIds: ['ab'], updatedEdgeIds: ['bc'], removedEdgeIds: ['ac'] } })
    expect(nodeRows(wrapper).map(node => [node.class, node.data.status, node.data.label])).toEqual([
      ['difference-added', 'snapshot', '新增 · 快照'], ['difference-updated', 'snapshot', '调整 · 快照'],
      ['difference-removed', 'snapshot', '移除 · 快照']
    ])
    const edges = flow(wrapper).props('edges')
    expect(edges.map((edge: any) => edge.label)).toEqual(['新增', '调整', '移除'])
    expect(edges[0].style.stroke).toContain('--sem-success')
    expect(edges[1].style.stroke).toContain('--sem-waiting')
    expect(edges[2].style).toMatchObject({ strokeDasharray: '6 5', opacity: 0.95 })
    expect(edges[2].style.stroke).toContain('--sem-failed')
    await wrapper.setProps({ historical: false })
    expect(nodeRows(wrapper).find(node => node.id === 'a').data.status).toBe('running')
    expect(nodeRows(wrapper).find(node => node.id === 'c').data.status).toBe('snapshot')
  })
  it('resets dragged positions and expansion on version changes, preserving them on status refresh', async () => {
    const wrapper = setup()
    await wrapper.setProps({ blueprint: { ...blueprint, graphVersion: 1 } })
    const drag = api.onNodeDragStop.mock.calls[0][0]
    drag({ node: { id: 'a', position: { x: 500, y: 500 } } })
    await wrapper.setProps({ blueprint: { ...blueprint, graphVersion: 1 }, statuses: { a: { status: 'completed', label: '已完成' } } })
    expect(nodeRows(wrapper).find(node => node.id === 'a').position.x).toBe(500)
    const node = wrapper.findAllComponents({ name: 'AcgExecutionNode' }).find(node => node.props('id') === 'b')!
    node.vm.$emit('toggle')
    await flushPromises()
    expect(node.props('expanded')).toBe(true)
    await wrapper.setProps({ blueprint: { ...blueprint, graphVersion: 2 } })
    await flushPromises()
    expect(nodeRows(wrapper).find(node => node.id === 'a').position.x).toBe(-160)
    expect(node.props('expanded')).toBe(false)
    expect(api.setCenter).toHaveBeenLastCalledWith(0, 0, { zoom: 1, duration: 0 })
  })
})
