import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AcgStepState, GraphProjection } from '@/services/api/agentos'
import { executionLayout } from '@/utils/acgExecutionLayout'
import AcgTopologyGraph from './AcgTopologyGraph.vue'

vi.mock('@/utils/acgExecutionLayout', async original => {
  const actual = await original<typeof import('@/utils/acgExecutionLayout')>()
  return { ...actual, executionLayout: vi.fn(actual.executionLayout) }
})

const { networks, flowCalls } = vi.hoisted(() => ({
  networks: [] as any[],
  flowCalls: { actualSize: vi.fn(), overview: vi.fn(), zoomBy: vi.fn() }
}))
vi.mock('./AcgExecutionFlow.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({
    props: ['blueprint', 'selectedId', 'anchorId', 'statuses', 'positions', 'difference', 'historical'],
    emits: ['select', 'doubleClick', 'zoom'],
    setup(props, { emit, slots, expose }) {
      expose({ ...flowCalls, close: () => emit('select', '') })
      return () => h('div', { class: 'mock-execution-flow' }, [
        ...props.blueprint.nodes.map((node: any) => h('button', {
          'data-node': node.nodeId,
          onClick: () => emit('select', props.selectedId === node.nodeId ? '' : node.nodeId)
        }, `${node.name} ${props.statuses[node.nodeId].label}`)),
        props.selectedId ? slots.detail?.() : null
      ])
    }
  }) }
})
vi.mock('vis-network', () => ({ Network: vi.fn(function (_element, data, options) {
  const instance = { data, options, on: vi.fn(), once: vi.fn(), destroy: vi.fn(), setOptions: vi.fn(),
    selectNodes: vi.fn(), unselectAll: vi.fn(), redraw: vi.fn(), fit: vi.fn(), moveTo: vi.fn(),
    getScale: () => 1, getViewPosition: () => ({ x: 0, y: 0 }) }
  networks.push(instance)
  return instance
}) }))
vi.mock('@/services/api/workflow', () => ({ workflowApi: { listRunResourceCalls: vi.fn(async () => ({
  items: [{ callId: 'c1', stepId: 'n3', model: 'glm-4', usage: {
    inputTokens: 100, outputTokens: 50, cacheReadTokens: 40, totalTokens: 150
  } }], nextCursor: null, total: 1
})) } }))
const blueprint: GraphProjection = {
  graphId: 'execution-preview',
  nodes: [1, 2, 3, 4, 5].map(i => ({ nodeId: `n${i}`, nodeType: 'step', name: `Task ${i}` })),
  edges: [1, 2, 3, 4].map(i => ({ edgeId: `e${i}`, sourceId: `n${i}`, targetId: `n${i + 1}`, edgeType: 'dependency' }))
}
const wrappers: ReturnType<typeof mount>[] = []
const failedStepStates = [{ stepId: 'n3', status: 'failed', agentName: 'worker', attempt: 1, retryCount: 0 }]
const setup = async (extra = {}) => {
  const wrapper = mount(AcgTopologyGraph, {
    props: { blueprint, workbench: true, observeResize: true, runtimePhases: { n3: 'running' }, ...extra },
    global: { stubs: { ElIcon: { template: '<span><slot /></span>' } } }
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
const click = async (wrapper: ReturnType<typeof mount>, label: string) => {
  await wrapper.findAll('button').find(button => button.text() === label)!.trigger('click')
  await flushPromises()
  await vi.advanceTimersByTimeAsync(150)
}
const ids = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('[data-node]').map(node => node.attributes('data-node'))
beforeEach(() => { vi.useFakeTimers(); networks.length = 0; vi.clearAllMocks() })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers() })

describe('execution flow integration', () => {
  it('reuses layout across fresh runtime snapshots and recomputes only when layout inputs change', async () => {
    const state: AcgStepState = { stepId: 'n3', status: 'running', agentName: 'worker', attempt: 1, retryCount: 0,
      task: { taskId: 'task', missionId: 'mission', title: 'Task', objective: '', constraints: [], status: 'running',
        metadata: {}, parentTaskId: 'parent-1' } }
    const wrapper = await setup({ stepStates: [state] })
    const flow = wrapper.findComponent('.mock-execution-flow')
    const positions = flow.props('positions')
    expect(executionLayout).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ stepStates: [{ ...state, status: 'completed', attempt: 2, outputSummary: 'Updated evidence',
      task: { ...state.task!, status: 'completed', title: 'Updated task label' } }],
      runtimePhases: { n3: 'COMPLETED' }, completedStepIds: ['n3'],
      blueprint: { ...blueprint, nodes: blueprint.nodes.map(node => ({ ...node, name: `${node.name} updated` })),
        edges: [...blueprint.edges].reverse().map(edge => ({ ...edge })) } })
    expect(executionLayout).toHaveBeenCalledTimes(1)
    expect(flow.props('positions')).toBe(positions)
    expect(flow.props('statuses').n3.status).toBe('completed')

    await wrapper.setProps({ stepStates: [{ ...state, task: { ...state.task!, parentTaskId: 'parent-2' } }] })
    expect(executionLayout).toHaveBeenCalledTimes(2)
    expect(flow.props('positions')).not.toBe(positions)

    const reordered = { ...blueprint, nodes: blueprint.nodes.map((node, index) => ({ ...node, display: { displayOrder: 5 - index } })) }
    await wrapper.setProps({ blueprint: reordered })
    expect(executionLayout).toHaveBeenCalledTimes(3)
    const dependencyChanged = { ...reordered, edges: reordered.edges.map((edge, index) => index === 0 ? { ...edge, targetId: 'n4' } : edge) }
    await wrapper.setProps({ blueprint: dependencyChanged })
    expect(executionLayout).toHaveBeenCalledTimes(4)
    await wrapper.setProps({ blueprint: { ...dependencyChanged, nodes: [...dependencyChanged.nodes].reverse() } })
    expect(executionLayout).toHaveBeenCalledTimes(5)
  })
  it('keeps recovered pending nodes idle despite old streaming phases', async () => {
    const wrapper = await setup({ runtimePhases: { n3: 'STREAMING' },
      stepStates: [{ stepId: 'n3', status: 'pending', agentName: 'worker', attempt: 2, retryCount: 1 }] })
    await click(wrapper, '全部步骤')
    const flow = wrapper.findComponent('.mock-execution-flow')
    expect(flow.props('statuses').n3).toMatchObject({ status: 'pending', label: '待执行' })
    expect(wrapper.get('[data-node="n3"]').text()).not.toContain('运行中')
    await wrapper.setProps({ stepStates: [{ stepId: 'n3', status: 'running', agentName: 'worker', attempt: 2, retryCount: 1 }] })
    expect(flow.props('statuses').n3).toMatchObject({ status: 'running', label: '运行中' })
  })
  it('retains the topology renderer and camera when its Workbench is cached', async () => {
    const visible = ref(true)
    const phases = ref<Record<string, string>>({})
    const host = defineComponent({ setup: () => () => h(KeepAlive, null, { default: () => visible.value
      ? h(AcgTopologyGraph, { blueprint, workbench: true, observeResize: true, runtimePhases: phases.value, stepStates: failedStepStates }) : null }) })
    const wrapper = mount(host, { global: { stubs: { ElIcon: true } } }); wrappers.push(wrapper)
    await flushPromises()
    await click(wrapper, '异常路径')
    const uid = wrapper.findComponent(AcgTopologyGraph).vm.$.uid
    const network = networks[0]
    network.getScale = () => 1.7; network.getViewPosition = () => ({ x: 80, y: 120 })
    network.moveTo.mockClear()
    visible.value = false; await nextTick()
    phases.value.n3 = 'running'
    await vi.advanceTimersByTimeAsync(150)
    visible.value = true; await nextTick(); await flushPromises()
    expect(wrapper.findComponent(AcgTopologyGraph).vm.$.uid).toBe(uid)
    expect(networks).toHaveLength(1); expect(network.destroy).not.toHaveBeenCalled()
    expect(network.getScale()).toBe(1.7); expect(network.getViewPosition()).toEqual({ x: 80, y: 120 })
    expect(network.moveTo).not.toHaveBeenCalled()
  })
  it('renders all steps by default and switches to the running neighborhood without creating a canvas network', async () => {
    const wrapper = await setup()
    await vi.advanceTimersByTimeAsync(150)
    expect(ids(wrapper)).toHaveLength(5)
    await click(wrapper, '当前步骤及关联')
    expect(ids(wrapper)).toEqual(['n2', 'n3', 'n4'])
    expect(wrapper.get('[data-node="n3"]').text()).toContain('\u8fd0\u884c\u4e2d')
    expect(networks).toHaveLength(0)
  })
  it('routes overview and actual-size controls to the execution flow', async () => {
    const wrapper = await setup()
    await click(wrapper, '\u5168\u90e8\u6b65\u9aa4')
    expect(ids(wrapper)).toHaveLength(5)
    await wrapper.get('.graph-fab__ball').trigger('click')
    await click(wrapper, '\u5168\u56fe\u603b\u89c8')
    expect(flowCalls.overview).toHaveBeenCalled()
    await click(wrapper, '\u5b9e\u9645\u5927\u5c0f')
    expect(flowCalls.actualSize).toHaveBeenCalledWith('n3', 240)
    await click(wrapper, '\u5b9a\u4f4d\u4efb\u52a1')
    expect(ids(wrapper)).toEqual(['n2', 'n3', 'n4'])
  })
  it('updates runtime statuses without resetting the viewport', async () => {
    const wrapper = await setup()
    await wrapper.setProps({ runtimePhases: { n2: 'completed', n3: 'running' } })
    expect(wrapper.get('[data-node="n2"]').text()).toContain('\u5df2\u5b8c\u6210')
    expect(flowCalls.actualSize).not.toHaveBeenCalled()
  })
  it.each([
    ['completed', '已完成'], ['skipped_by_condition', '已跳过'], ['cancelled', '已取消'], ['pending', '已完成']
  ])('preserves the durable %s outcome when an earlier attempt still has a FAILED stream phase', async (status, label) => {
    const wrapper = await setup({ observeResize: false, completedStepIds: ['n3'], runtimePhases: { n3: 'FAILED' },
      stepStates: [{ stepId: 'n3', status, agentName: 'worker', attempt: 1, retryCount: 1,
        errorSummary: 'Earlier attempt failed' }] })
    expect(wrapper.get('[data-node="n3"]').text()).toContain(label)
    expect(wrapper.get('[data-node="n3"]').text()).not.toContain('失败')
    await wrapper.get('[data-node="n3"]').trigger('click')
    expect(wrapper.get('.uml-card__status').text()).toBe(label)
    if (status === 'completed') {
      await click(wrapper, '异常路径')
      expect(wrapper.text()).toContain('当前运行没有异常路径')
    }
  })
  it('anchors the durable running supplemental read before old stream activity and earlier retry states', async () => {
    const revised: GraphProjection = { ...blueprint, graphVersion: 2,
      nodes: Array.from({ length: 10 }, (_, index) => ({ nodeId: `n${index + 1}`, nodeType: 'step' as const, name: `Task ${index + 1}` })),
      edges: Array.from({ length: 9 }, (_, index) => ({ edgeId: `e${index + 1}`, sourceId: `n${index + 1}`,
        targetId: `n${index + 2}`, edgeType: 'dependency' as const })) }
    const wrapper = await setup({ blueprint: revised, completedStepIds: ['n2'],
      runtimePhases: { n1: 'STREAMING', n2: 'FAILED', n3: 'FAILED', n9: 'FAILED' },
      stepStates: [{ stepId: 'n2', status: 'completed', agentName: 'worker', attempt: 1, retryCount: 1 },
        { stepId: 'n3', status: 'retrying', agentName: 'worker', attempt: 1, retryCount: 1 },
        { stepId: 'n9', status: 'running', agentName: 'worker', attempt: 1, retryCount: 0 }] })
    await click(wrapper, '当前步骤及关联')
    expect(ids(wrapper)).toEqual(['n8', 'n9', 'n10'])
    const flow = wrapper.findComponent('.mock-execution-flow')
    expect(flow.props('anchorId')).toBe('n9')
    expect(flow.props('statuses')).toMatchObject({ n2: { status: 'completed' }, n3: { status: 'retrying' }, n9: { status: 'running' } })
    expect(wrapper.get('[data-node="n9"]').text()).toContain('运行中')
  })
  it('follows an external selection outside the current neighborhood', async () => {
    const wrapper = await setup()
    await wrapper.setProps({ focusNodeId: 'n5' })
    await flushPromises()
    expect(ids(wrapper)).toEqual(['n4', 'n5'])
    expect(flowCalls.actualSize).toHaveBeenCalledWith('n5')
    expect(wrapper.emitted('nodeSelected')).toContainEqual(['n5'])
  })
  it('recenters an explicitly located node repeatedly without animating its selection echo', async () => {
    const wrapper = await setup()
    await wrapper.vm.focusNode('n5')
    expect(flowCalls.actualSize.mock.calls).toEqual([['n5']])
    await wrapper.setProps({ focusNodeId: 'n5' })
    await flushPromises()
    expect(flowCalls.actualSize).toHaveBeenCalledTimes(1)
    await wrapper.vm.focusNode('n5')
    expect(flowCalls.actualSize.mock.calls).toEqual([['n5'], ['n5']])
    expect(ids(wrapper)).toEqual(['n4', 'n5'])
  })
  it('returns from an abnormal path to the current execution and can locate it repeatedly', async () => {
    const wrapper = await setup({ stepStates: failedStepStates })
    await click(wrapper, '异常路径')
    expect(networks).toHaveLength(1)
    await wrapper.vm.locateCurrentTask()
    expect(networks[0].destroy).toHaveBeenCalledTimes(1)
    expect(ids(wrapper)).toEqual(['n2', 'n3', 'n4'])
    expect(flowCalls.actualSize.mock.calls).toEqual([['n3', 240]])
    await wrapper.vm.locateCurrentTask()
    expect(flowCalls.actualSize.mock.calls).toEqual([['n3', 240], ['n3', 240]])
  })
  it('puts token usage and dependency navigation inside the expanded node', async () => {
    const wrapper = await setup({ runId: 'run-flow' })
    await wrapper.get('[data-node="n3"]').trigger('click')
    await flushPromises()
    const card = wrapper.get('.mock-execution-flow .uml-card')
    expect(card.text()).toContain('glm-4')
    expect(card.text()).toContain('150')
    expect(card.text()).toContain('60')
    expect(card.text()).toContain('40')
    expect(wrapper.find('.node-detail').exists()).toBe(false)
    await card.get('.uml-card__dep-group button').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('nodeSelected')).toContainEqual(['n2'])
    await wrapper.get('[aria-label="\u6536\u8d77\u8282\u70b9\u8be6\u60c5"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.uml-card').exists()).toBe(false)
  })
  it('keeps the abnormal-path view on the existing network renderer', async () => {
    const wrapper = await setup({ stepStates: failedStepStates })
    await click(wrapper, '\u5f02\u5e38\u8def\u5f84')
    expect(wrapper.find('.mock-execution-flow').exists()).toBe(false)
    expect(networks).toHaveLength(1)
    expect(networks[0].data.nodes.getIds()).toEqual(['n2', 'n3', 'n4'])
    expect(networks[0].options.physics.enabled).toBe(true)
  })
  it('shows the empty hint when no abnormal steps exist', async () => {
    const wrapper = await setup()
    await click(wrapper, '\u5f02\u5e38\u8def\u5f84')
    expect(wrapper.text()).toContain('\u5f53\u524d\u8fd0\u884c\u6ca1\u6709\u5f02\u5e38\u8def\u5f84')
  })
  it('can close full execution details after expanding a node', async () => {
    const wrapper = await setup({ stepStates: [{ stepId: 'n3', status: 'running', agentName: 'worker', attempt: 1, retryCount: 0 }] })
    await wrapper.get('[data-node="n3"]').trigger('click')
    await wrapper.get('.uml-card__more').trigger('click')
    expect(wrapper.find('.node-detail').exists()).toBe(true)
    await wrapper.get('.node-detail > header button').trigger('click')
    expect(wrapper.find('.node-detail').exists()).toBe(false)
    expect(wrapper.find('.uml-card').exists()).toBe(false)
  })
  it('shows historical structure without current execution status or live detail records', async () => {
    const wrapper = await setup({ historical: true, runId: 'live-run', stepStates: failedStepStates })
    expect(ids(wrapper)).toHaveLength(5)
    expect(wrapper.text()).toContain('历史结构快照')
    expect(wrapper.findAll('button').some(button => button.text() === '异常路径')).toBe(false)
    expect(wrapper.get('[data-node="n3"]').text()).toContain('快照')
    expect(wrapper.get('[data-node="n3"]').text()).not.toContain('运行中')
    await wrapper.get('[data-node="n3"]').trigger('click')
    expect(wrapper.get('.uml-card').text()).not.toContain('Token 消耗')
    expect(wrapper.get('.uml-card').text()).not.toContain('尚未产出')
    expect(wrapper.find('.uml-card__more').exists()).toBe(false)
  })
  it('clears selection when switching versions of the same graph and passes structural differences', async () => {
    const wrapper = await setup({ blueprint: { ...blueprint, graphVersion: 1 } })
    await wrapper.get('[data-node="n3"]').trigger('click')
    expect(wrapper.find('.uml-card').exists()).toBe(true)
    await wrapper.setProps({ runtimePhases: { n3: 'completed' } })
    expect(wrapper.find('.uml-card').exists()).toBe(true)
    const difference = { addedNodeIds: ['n5'], updatedNodeIds: ['n3'], removedNodeIds: ['n1'],
      addedEdgeIds: ['e4'], updatedEdgeIds: [], removedEdgeIds: ['e1'] }
    await wrapper.setProps({ blueprint: { ...blueprint, graphVersion: 2 }, difference })
    expect(wrapper.find('.uml-card').exists()).toBe(false)
    expect(ids(wrapper)).toHaveLength(5)
    expect(wrapper.find('[aria-label="图结构变更图例"]').text()).toBe('新增调整移除')
    expect(wrapper.findComponent('.mock-execution-flow').props('difference')).toEqual(difference)
  })
})
