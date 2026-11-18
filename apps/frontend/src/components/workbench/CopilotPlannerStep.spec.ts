import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CopilotPlannerStep from './CopilotPlannerStep.vue'

afterEach(() => vi.unstubAllGlobals())

function followLayout() {
  let nextId = 0
  const frames = new Map<number, FrameRequestCallback>()
  const request = vi.fn((callback: FrameRequestCallback) => { const id = ++nextId; frames.set(id, callback); return id })
  vi.stubGlobal('requestAnimationFrame', request)
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
  const observers = new Set<ResizeObserverCallback>()
  const disconnected = vi.fn()
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: ResizeObserverCallback) { observers.add(callback) }
    observe() {}
    disconnect() { observers.delete(this.callback); disconnected() }
  })
  return { frames, request, disconnected,
    flush() { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback(0)) },
    resize() { [...observers].forEach(callback => callback([], {} as ResizeObserver)) },
  }
}

describe('planner transcript step', () => {
  it('summarizes a completed checklist and keeps the complete record folded', async () => {
    const reasoning = '根目录缺少依赖清单（已确认）\n\npackages/chat-stream 为空（已确认）\nNode 进程入口（已确认）\n前端接口边界（已确认）'
    const w = mount(CopilotPlannerStep, { props: { id: 'checks', execution: true, state: 'streaming', text: '', reasoning } })
    expect(w.find('.planner-step__checklist').exists()).toBe(false)
    await w.setProps({ state: 'completed' })
    expect(w.attributes('open')).toBeDefined()
    expect(w.get('.planner-step__state').text()).toBe('4 项已确认')
    expect(w.get('.planner-step__checklist code').text()).toBe('packages/chat-stream')
    expect(w.get('.planner-step__checklist').text()).not.toContain('（已确认）')
    expect(w.get('.planner-step__raw').attributes('open')).toBeUndefined()
    expect(w.get('.planner-step__raw').text()).toContain('Node 进程入口（已确认）')
    await w.setProps({ reasoning: reasoning.replace('入口（已确认）', '入口（待核实）') })
    expect(w.get('.planner-step__state').text()).toBe('3/4 项已确认')
    expect(w.get('.planner-step__exception').text()).toBe('待核实')
    w.unmount()
  })

  it('shows the model reasoning directly and keeps draft fields behind a separate disclosure', async () => {
    const w = mount(CopilotPlannerStep, { props: { id: 'outline', stage: 'outline', state: 'streaming', text: '' } })
    expect(w.attributes('open')).toBeDefined()
    expect(w.text()).toContain('模型尚未返回思考过程')
    await w.setProps({ reasoning: '先核对**跨校区权限**，再拆分任务。', text: '功能性需求规格\n\n每条需求可验证' })
    expect(w.get('.planner-step__reasoning strong').text()).toBe('跨校区权限')
    expect(w.get('.planner-step__reasoning').text()).not.toContain('每条需求可验证')
    expect(w.get('.planner-step__draft').attributes('open')).toBeUndefined()
    expect(w.get('.planner-step__draft').text()).toContain('每条需求可验证')
    await w.setProps({ state: 'completed', elapsedMs: 1250 })
    expect(w.attributes('open')).toBeUndefined()
    expect(w.get('summary').text()).toContain('已返回')
    expect(w.get('summary').text()).toContain('1.3 秒')
    // A finished provider call is not an accepted plan.
    expect(w.text()).toContain('以待确认的初步规划为准')
    w.unmount()
  })

  it('preserves manual folding across chunks and distinguishes retries from accepted results', async () => {
    const w = mount(CopilotPlannerStep, { props: { id: 'detail', stage: 'detail:2.repair', state: 'streaming', text: '草稿', reasoning: '先核对输入' } })
    ;(w.element as HTMLDetailsElement).open = false
    await w.trigger('toggle')
    await w.setProps({ reasoning: '先核对输入，再检查依赖' })
    expect(w.attributes('open')).toBeUndefined()
    await w.setProps({ state: 'retrying' })
    expect(w.get('summary').text()).toContain('补充步骤目标与验收标准 · 修正')
    expect(w.get('summary').text()).toContain('已重试')
    expect(w.text()).toContain('此段输出已中断')
    expect(w.text()).toContain('已收到的思考记录保留在这里')
    w.unmount()
  })

  it('opens interrupted records for inspection without rendering returned HTML', () => {
    const w = mount(CopilotPlannerStep, { props: { id: 'failed', stage: 'relations', state: 'interrupted', text: '', reasoning: '<script>alert(1)</script>\n\n依赖检查未完成' } })
    expect(w.attributes('open')).toBeDefined()
    expect(w.text()).toContain('已中断')
    expect(w.find('script').exists()).toBe(false)
    w.unmount()
  })
  it('does not substitute task fields for missing thinking and marks truncated thought records', async () => {
    const w = mount(CopilotPlannerStep, { props: { id: 'no-thought', state: 'completed', text: '验收条件：每条需求可验证' } })
    expect(w.get('.planner-step__reasoning').text()).toBe('本轮模型未返回思考过程。')
    await w.setProps({ reasoning: '最新思考片段', reasoningTruncated: true })
    expect(w.get('.planner-step__reasoning').text()).toContain('最新片段')
    w.unmount()
  })

  it('keeps streaming reasoning pinned to the tail until the reader takes over', async () => {
    const layout = followLayout()
    const metrics = { scrollHeight: 1200 }
    const w = mount(CopilotPlannerStep, { props: { id: 'follow', state: 'streaming', text: '', reasoning: '第一段思考' } })
    const view = w.get('.planner-step__body').element as HTMLElement
    Object.defineProperty(view, 'scrollHeight', { configurable: true, get: () => metrics.scrollHeight })
    Object.defineProperty(view, 'clientHeight', { configurable: true, get: () => 320 })
    expect(w.find('.planner-step__resume').exists()).toBe(false)
    await w.vm.$nextTick()
    layout.flush()
    expect(view.scrollTop).toBe(1200)
    metrics.scrollHeight = 2600
    await w.setProps({ reasoning: '第一段思考，继续生成更多内容' })
    layout.flush()
    expect(view.scrollTop).toBe(2600)
    await w.get('.planner-step__body').trigger('wheel')
    expect(w.find('.planner-step__resume').exists()).toBe(true)
    metrics.scrollHeight = 3400
    await w.setProps({ reasoning: '第一段思考，继续生成更多内容。' })
    layout.flush()
    expect(view.scrollTop).toBe(2600)
    await w.get('.planner-step__resume').trigger('click')
    expect(view.scrollTop).toBe(3400)
    expect(w.find('.planner-step__resume').exists()).toBe(false)
    await w.get('.planner-step__body').trigger('wheel')
    expect(w.find('.planner-step__resume').exists()).toBe(true)
    view.scrollTop = 3080
    await w.get('.planner-step__body').trigger('scroll')
    expect(w.find('.planner-step__resume').exists()).toBe(false)
    w.unmount()
  })

  it('follows delayed content growth once without scheduling idle layout work', async () => {
    const layout = followLayout()
    const w = mount(CopilotPlannerStep, { props: { id: 'resize', state: 'streaming', text: '', reasoning: '首段内容' } })
    const view = w.get('.planner-step__body').element as HTMLElement
    let height = 1200
    const readHeight = vi.fn(() => height)
    Object.defineProperty(view, 'scrollHeight', { configurable: true, get: readHeight })
    await w.vm.$nextTick()
    layout.flush()
    expect(view.scrollTop).toBe(1200)
    expect(layout.frames.size).toBe(0)
    const requested = layout.request.mock.calls.length
    layout.flush()
    expect(layout.request).toHaveBeenCalledTimes(requested)
    expect(readHeight).toHaveBeenCalledOnce()
    height = 2600
    layout.resize()
    layout.resize()
    await w.setProps({ reasoning: '首段内容和后续内容' })
    expect(layout.frames.size).toBe(1)
    layout.flush()
    expect(view.scrollTop).toBe(2600)
    expect(readHeight).toHaveBeenCalledTimes(2)
    expect(layout.frames.size).toBe(0)
    w.unmount()
    expect(layout.disconnected).toHaveBeenCalledOnce()
  })

  it.each(['fold', 'complete', 'pause', 'unmount'])('cancels pending follow work on %s', async action => {
    const layout = followLayout()
    const w = mount(CopilotPlannerStep, { props: { id: 'cancel', state: 'streaming', text: '', reasoning: '正在生成' } })
    await w.vm.$nextTick()
    expect(layout.frames.size).toBe(1)
    if (action === 'fold') {
      ;(w.element as HTMLDetailsElement).open = false
      await w.trigger('toggle')
    } else if (action === 'complete') await w.setProps({ state: 'completed' })
    else if (action === 'pause') await w.get('.planner-step__body').trigger('wheel')
    else w.unmount()
    expect(layout.frames.size).toBe(0)
    layout.resize()
    expect(layout.frames.size).toBe(0)
    if (action !== 'unmount') w.unmount()
  })
})
