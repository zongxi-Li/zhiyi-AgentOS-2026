import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GraphProjection } from '@/services/api/agentos'
import AcgTopologyGraph from './AcgTopologyGraph.vue'

const { networks } = vi.hoisted(() => ({ networks: [] as any[] }))
vi.mock('vis-network', () => ({
  Network: vi.fn(function (_element, data, options) {
    const instance = {
      data, options, on: vi.fn(), once: vi.fn(), destroy: vi.fn(), setOptions: vi.fn(),
      selectNodes: vi.fn(), unselectAll: vi.fn(), redraw: vi.fn(), fit: vi.fn(),
      moveTo: vi.fn(), focus: vi.fn(), getScale: () => 1, getViewPosition: () => ({ x: 0, y: 0 }),
      canvasToDOM: (position: { x: number; y: number }) => position,
      getPositions: (ids: string[]) => Object.fromEntries(ids.map(id => [id, { x: data.nodes.get(id)?.x || 0, y: data.nodes.get(id)?.y || 0 }]))
    }
    networks.push(instance)
    return instance
  })
}))
vi.mock('@/services/api/workflow', () => ({
  workflowApi: {
    listRunResourceCalls: vi.fn(async (runId: string) => ({
      runId,
      items: [{
        callId: 'c1', stepId: 'n3', model: 'glm-4',
        usage: { inputTokens: 100, outputTokens: 50, cacheReadTokens: 40, cacheWriteTokens: 0, reasoningTokens: 0, totalTokens: 150 }
      }],
      nextCursor: null,
      total: 1
    }))
  }
}))

const blueprint: GraphProjection = {
  graphId: 'execution-preview',
  nodes: [1, 2, 3, 4, 5].map(i => ({ nodeId: `n${i}`, nodeType: 'step', name: `任务 ${i}` })),
  edges: [1, 2, 3, 4].map(i => ({ edgeId: `e${i}`, sourceId: `n${i}`, targetId: `n${i + 1}`, edgeType: 'dependency' }))
}
const wrappers: ReturnType<typeof mount>[] = []
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
const ids = () => networks[networks.length - 1].data.nodes.getIds().sort()

beforeEach(() => { vi.useFakeTimers(); networks.length = 0 })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers() })

describe('execution graph reading controls', () => {
  it('starts at readable scale around the running task and shows the reduced scope', async () => {
    await setup()
    expect(ids()).toEqual(['n2', 'n3', 'n4'])
    expect(networks[0].options.physics.enabled).toBe(false)
    expect(networks[0].moveTo).toHaveBeenCalledWith(expect.objectContaining({ scale: 1 }))
  })

  it('distinguishes all steps at actual size from fitting the overview', async () => {
    const wrapper = await setup()
    await click(wrapper, '全部步骤')
    expect(ids()).toEqual(['n1', 'n2', 'n3', 'n4', 'n5'])
    expect(networks[networks.length - 1].fit).not.toHaveBeenCalled()
    await wrapper.find('button.graph-fab__ball').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(150)
    await click(wrapper, '全图总览')
    expect(networks[networks.length - 1].fit).toHaveBeenCalled()
    await click(wrapper, '定位任务')
    expect(ids()).toEqual(['n2', 'n3', 'n4'])
  })

  it('recognizes the runtime event store streaming phase as the active task', async () => {
    await setup({ runtimePhases: { n1: 'WAITING', n2: 'COMPLETED', n4: 'STREAMING' } })
    expect(ids()).toEqual(['n3', 'n4', 'n5'])
    expect(networks[0].data.nodes.get('n4').label).toContain('运行中')
  })

  it('can follow an external selection outside the current neighborhood', async () => {
    const wrapper = await setup()
    await wrapper.setProps({ focusNodeId: 'n5' })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(150)
    expect(ids()).toEqual(['n4', 'n5'])
    expect(networks[networks.length - 1].focus).toHaveBeenCalledWith('n5', { scale: 1, animation: true })
    expect(wrapper.emitted('nodeSelected')).toContainEqual(['n5'])
  })

  it('updates runtime labels without rebuilding a stable graph or resetting the camera', async () => {
    const wrapper = await setup()
    const initial = networks[0]
    initial.moveTo.mockClear()
    await wrapper.setProps({ runtimePhases: { n2: 'completed', n3: 'running' } })
    await vi.advanceTimersByTimeAsync(150)
    expect(networks).toHaveLength(1)
    expect(initial.data.nodes.get('n2').label).toContain('已完成')
    expect(initial.moveTo).not.toHaveBeenCalled()
  })

  it('retains the full graph and force layout in the complete topology view', async () => {
    const wrapper = await setup()
    await click(wrapper, '完整拓扑')
    expect(ids()).toHaveLength(5)
    expect(networks[networks.length - 1].options.physics.enabled).toBe(true)
    expect(wrapper.find('[aria-label="执行链范围"]').exists()).toBe(false)
  })
})

describe('UML node detail card', () => {
  const emitNetworkEvent = (event: 'selectNode' | 'click', nodeId: string) => {
    const network = networks[networks.length - 1]
    const handler = network.on.mock.calls.find(([name]) => name === event)?.[1]
    handler?.({ nodes: [nodeId] })
  }

  it('expands a detail card under the selected node and collapses on re-click', async () => {
    const wrapper = await setup()
    emitNetworkEvent('selectNode', 'n3')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(150)
    const card = wrapper.find('[aria-label="节点详情卡片"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('Token 消耗')
    expect(card.text()).toContain('当前视图未关联 Run')
    expect(card.text()).toContain('输入 · 1')
    expect(card.text()).toContain('输出 · 1')
    expect(wrapper.find('.node-detail').exists()).toBe(false)
    emitNetworkEvent('click', 'n3')
    await flushPromises()
    expect(wrapper.find('[aria-label="节点详情卡片"]').exists()).toBe(false)
    expect(wrapper.emitted('nodeSelected')?.at(-1)).toEqual(['n3'])
  })

  it('shows per-node token usage from run model calls', async () => {
    const wrapper = await setup({ runId: 'run_uml' })
    await flushPromises()
    emitNetworkEvent('selectNode', 'n3')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(150)
    const card = wrapper.find('[aria-label="节点详情卡片"]')
    expect(card.text()).toContain('1 次调用')
    expect(card.text()).toContain('60')
    expect(card.text()).toContain('40')
    expect(card.text()).toContain('50')
    expect(card.text()).toContain('150')
    expect(card.text()).toContain('glm-4')
    emitNetworkEvent('selectNode', 'n2')
    await flushPromises()
    expect(wrapper.find('[aria-label="节点详情卡片"]').text()).toContain('未观测到模型调用')
  })

  it('keeps the card out of the complete topology view where the side panel still applies', async () => {
    const wrapper = await setup()
    await click(wrapper, '完整拓扑')
    emitNetworkEvent('selectNode', 'n3')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(150)
    expect(wrapper.find('[aria-label="节点详情卡片"]').exists()).toBe(false)
    expect(wrapper.find('.node-detail').exists()).toBe(true)
  })

  it('pushes same-column nodes down while expanded and restores them on collapse', async () => {
    const branchBlueprint: GraphProjection = {
      graphId: 'branch',
      nodes: [{ nodeId: 'a', nodeType: 'step', name: '任务 A' }, { nodeId: 'b', nodeType: 'step', name: '任务 B' }, { nodeId: 'c', nodeType: 'step', name: '任务 C' }],
      edges: [
        { edgeId: 'e1', sourceId: 'a', targetId: 'b', edgeType: 'dependency' },
        { edgeId: 'e2', sourceId: 'a', targetId: 'c', edgeType: 'dependency' }
      ]
    }
    const wrapper = await setup({ blueprint: branchBlueprint, runtimePhases: {} })
    const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')!
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 300 })
    try {
      emitNetworkEvent('selectNode', 'b')
      await flushPromises()
      await vi.advanceTimersByTimeAsync(200)
      expect(wrapper.find('[aria-label="节点详情卡片"]').exists()).toBe(true)
      const pushed = networks[networks.length - 1].data.nodes.get('c')
      expect(pushed.y).toBeGreaterThan(80)
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', descriptor)
    }
    emitNetworkEvent('click', 'b')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(200)
    expect(networks[networks.length - 1].data.nodes.get('c').y).toBe(80)
  })
})
