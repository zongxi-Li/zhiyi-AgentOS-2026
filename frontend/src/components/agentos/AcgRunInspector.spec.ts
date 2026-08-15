import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AcgRunInspector from './AcgRunInspector.vue'

describe('AcgRunInspector', () => {
  it('does not invent metrics before a run starts', () => {
    const wrapper = mount(AcgRunInspector)
    expect(wrapper.text()).not.toContain('0%')
  })

  it('projects real graph, progress and provenance-derived metrics', async () => {
    const wrapper = mount(AcgRunInspector, { props: {
      runId: 'run_1234567890abcdef', status: 'running', statusLabel: 'running',
      progress: { message: 'evidence review', percent: 50, totalSteps: 4, completedSteps: 2,
        runningSteps: 1, waitingReviewSteps: 1, failedSteps: 0, currentStepId: 'evidence_verify' } as any,
      blueprint: { nodes: [{ nodeId: 'n1' }, { nodeId: 'n2' }, { nodeId: 'n3' }],
        edges: [{ edgeId: 'e1' }, { edgeId: 'e2' }] } as any,
      view: { lowEntropyMetrics: { averageSavingRatio: 0.2, effectiveSavingRatio: 0.25,
        tokensAvailable: 2000, tokensDelivered: 1500, tokensSaved: 500,
        recoveryCount: 1, interactionCount: 6, contractViolationCount: 0,
        integrityStatus: 'valid' } } as any
    } })
    expect(wrapper.text()).toContain('evidence review')
    expect(wrapper.text()).toContain('25.0%')
    expect(wrapper.text()).not.toContain('2 新增')
    const buttons = wrapper.findAll('.inspector-actions button')
    await buttons[0].trigger('click')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('open-acg')).toHaveLength(1)
    expect(wrapper.emitted('open-console')).toHaveLength(1)
  })
})
