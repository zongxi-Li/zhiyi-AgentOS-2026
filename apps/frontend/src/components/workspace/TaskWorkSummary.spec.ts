import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import TaskWorkSummary from './TaskWorkSummary.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers() })

describe('public task approach and model activity', () => {
  it('shows the accepted approach before the first token and updates the actual waiting duration', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-14T10:00:00Z'))
    const store = new RunRuntimeStore('run')
    store.apply({ eventId: 'start', runId: 'run', nodeId: 'node', sequence: 1, eventType: 'model.started', timestamp: new Date().toISOString() })
    const wrapper = mount(TaskWorkSummary, { props: { node: store.nodes.node, objective: '核对需求与验收标准', rationale: '先确认覆盖范围，再检查遗漏' } }); wrappers.push(wrapper)
    expect(wrapper.text()).toContain('来自已确认规划')
    expect(wrapper.text()).toContain('先确认覆盖范围，再检查遗漏')
    expect(wrapper.get('[role="status"]').text()).toContain('已等待 0 秒')
    await vi.advanceTimersByTimeAsync(65000)
    expect(wrapper.get('[role="status"]').text()).toContain('已等待 65 秒')
    store.apply({ eventId: 'activity', runId: 'run', nodeId: 'node', sequence: 2, eventType: 'model.activity', payload: { reasoning_content: 'PRIVATE' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[role="status"]').text()).toContain('已收到模型活动信号，正文尚未返回')
    expect(wrapper.text()).not.toContain('PRIVATE')
    store.apply({ eventId: 'first', runId: 'run', nodeId: 'node', sequence: 3, eventType: 'model.first_token' })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[role="status"]').text()).toContain('已收到模型正文')
    expect(wrapper.text()).not.toContain('已等待')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears previous activity for a new model turn and stops displaying progress after completion', async () => {
    const store = new RunRuntimeStore('run')
    const apply = (sequence: number, eventType: string) => store.apply({ eventId: `event-${sequence}`, runId: 'run', nodeId: 'node', sequence, eventType })
    apply(1, 'model.started'); apply(2, 'model.activity')
    const wrapper = mount(TaskWorkSummary, { props: { node: store.nodes.node } }); wrappers.push(wrapper)
    expect(wrapper.text()).toContain('已收到模型活动信号')
    apply(3, 'model.started'); await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('模型请求已发出')
    expect(wrapper.text()).not.toContain('已收到模型活动信号')
    apply(4, 'model.completed'); await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('正在校验步骤结果')
    expect(wrapper.text()).not.toContain('已等待')
    apply(5, 'node.completed'); await wrapper.vm.$nextTick()
    expect(wrapper.find('.task-work-summary').exists()).toBe(false)
  })
})
