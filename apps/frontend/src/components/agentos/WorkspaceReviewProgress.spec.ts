import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkspaceReviewProgress from './WorkspaceReviewProgress.vue'
import type { WorkspaceReviewProjection } from '@/services/api/agentos/types/graph'

export const review: WorkspaceReviewProjection = {
  schemaVersion: 1, round: 2, graphVersion: 3, status: 'reading',
  gaps: { missingReadCount: 105, missingListingCount: 8, unsupportedEntryCount: 1,
    missingReads: ['src/main.py'], missingListings: ['tests'], unsupportedEntries: ['link'] },
  rounds: [{ round: 1, graphVersion: 2, action: 'revise', reason: '补齐证据后重新复核',
    stepIds: ['read-1', 'review-1'], addedStepIds: ['read-1', 'review-1'],
    observationRef: 'observation:1', decisionRef: 'decision:1', patchRef: 'patch:1', traceRefs: ['trace:1'] }],
}

describe('runtime repository review progress', () => {
  it('shows authoritative counts independently of path samples and preserves round evidence', () => {
    const wrapper = mount(WorkspaceReviewProgress, { props: { review } })
    expect(wrapper.get('[role="status"]').text()).toContain('第 2 轮')
    expect(wrapper.get('[role="status"]').text()).toContain('图 v3')
    expect(wrapper.get('[role="status"]').text()).toContain('剩余目录 8 · 文件 105')
    expect(wrapper.text()).toContain('src/main.py')
    expect(wrapper.text()).toContain('补齐证据后重新复核')
    for (const reference of ['observation:1', 'decision:1', 'patch:1', 'trace:1']) expect(wrapper.text()).toContain(reference)
  })

  it('navigates only nodes that actually exist in the supplied formal graph', async () => {
    const nodes = [{ nodeId: 'read-1', name: '补读代码' }]
    const before = JSON.stringify({ review, nodes })
    const wrapper = mount(WorkspaceReviewProgress, { props: { review, nodes, navigable: true } })
    expect(wrapper.findAll('button')).toHaveLength(1)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('selectNode')).toEqual([['read-1']])
    expect(wrapper.text()).toContain('review-1')
    expect(JSON.stringify({ review, nodes })).toBe(before)
  })

  it('waits for a matching graph projection and does not invent review state', async () => {
    const wrapper = mount(WorkspaceReviewProgress, { props: { graphVersion: 3 } })
    expect(wrapper.find('section').exists()).toBe(false)
    await wrapper.setProps({ review, graphVersion: 2 })
    expect(wrapper.find('section').exists()).toBe(false)
    await wrapper.setProps({ graphVersion: 3 })
    expect(wrapper.find('section').exists()).toBe(true)
  })
})
