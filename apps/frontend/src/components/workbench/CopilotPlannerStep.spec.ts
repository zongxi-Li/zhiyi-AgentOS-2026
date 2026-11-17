import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CopilotPlannerStep from './CopilotPlannerStep.vue'

describe('planner transcript step', () => {
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
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(performance.now()), 16) as unknown as number)
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id as unknown as Parameters<typeof clearTimeout>[0]))
    const metrics = { scrollHeight: 1200 }
    const w = mount(CopilotPlannerStep, { props: { id: 'follow', state: 'streaming', text: '', reasoning: '第一段思考' } })
    const view = w.get('.planner-step__body').element as HTMLElement
    Object.defineProperty(view, 'scrollHeight', { configurable: true, get: () => metrics.scrollHeight })
    Object.defineProperty(view, 'clientHeight', { configurable: true, get: () => 320 })
    expect(w.find('.planner-step__resume').exists()).toBe(false)
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(view.scrollTop).toBe(1200)
    metrics.scrollHeight = 2600
    await w.setProps({ reasoning: '第一段思考，继续生成更多内容' })
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(view.scrollTop).toBe(2600)
    await w.get('.planner-step__body').trigger('wheel')
    expect(w.find('.planner-step__resume').exists()).toBe(true)
    metrics.scrollHeight = 3400
    await w.setProps({ reasoning: '第一段思考，继续生成更多内容。' })
    await new Promise(resolve => setTimeout(resolve, 30))
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
    vi.unstubAllGlobals()
  })
})
