import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AcgExecutionFlow from './AcgExecutionFlow.vue'

const { api } = vi.hoisted(() => ({ api: {
  setCenter: vi.fn(), fitView: vi.fn(), zoomTo: vi.fn(),
  viewport: { value: { zoom: 0.5 } },
  onInit: vi.fn(), onViewportChange: vi.fn(), onNodeDragStop: vi.fn()
} }))
vi.mock('@vue-flow/core', async () => {
  const { defineComponent, h } = await import('vue')
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
  it('does not move the camera on runtime status changes and uses flow viewport controls', async () => {
    const wrapper = setup()
    await wrapper.setProps({ statuses: { b: { status: 'completed', label: 'Completed' } } })
    expect(api.setCenter).not.toHaveBeenCalled()
    await wrapper.vm.actualSize('b', 0)
    expect(api.setCenter).toHaveBeenCalledWith(0, 0, { zoom: 1, duration: 0 })
    wrapper.vm.zoomBy(2)
    expect(api.zoomTo).toHaveBeenCalledWith(1, { duration: 180 })
  })
})
