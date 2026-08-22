import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RuntimeAuditTimeline from './RuntimeAuditTimeline.vue'

describe('RuntimeAuditTimeline', () => {
  it('combines trace, patch reference, checkpoint and review without legacy projections', () => {
    const wrapper = mount(RuntimeAuditTimeline, {
      props: {
        events: [{ eventId: 'event_1', runId: 'run_1', stepId: 'step_1', eventType: 'RUN_RECOVERED', createdAt: '2026-08-19T00:02:00Z' }],
        patchRefs: ['patch_1'],
        checkpoints: [{ checkpointId: 'checkpoint_1', version: 2, canResume: true }],
        reviews: [{ reviewId: 'review_1', runId: 'run_1', stepId: 'step_2', decision: 'approved', reviewer: 'operator', createdAt: '2026-08-19T00:03:00Z' }]
      }
    })
    expect(wrapper.text()).toContain('运行审计时间线')
    expect(wrapper.text()).toContain('运行恢复')
    expect(wrapper.text()).toContain('GraphPatch 引用')
    expect(wrapper.text()).toContain('Checkpoint')
    expect(wrapper.text()).toContain('人工审核')
    expect(wrapper.text()).not.toContain('runtimeGraph')
    expect(wrapper.text()).not.toContain('dynamicPatch')
  })

  it('uses the 执行运行时 empty state when no audit references exist', () => {
    const wrapper = mount(RuntimeAuditTimeline)
    expect(wrapper.text()).toContain('尚无 Trace、恢复、Checkpoint、Review 或 GraphPatch 引用')
  })
})
