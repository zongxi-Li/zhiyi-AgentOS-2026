import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ContractReviewReportMessage from './ContractReviewReportMessage.vue'

describe('ContractReviewReportMessage', () => {
  it('presents the report as a compact chat-native document with a rendered table', async () => {
    const wrapper = mount(ContractReviewReportMessage, {
      props: {
        report: [
          '# Contract review report',
          '',
          '| Risk | Recommendation |',
          '| --- | --- |',
          '| Payment | Reduce the advance payment ratio. |'
        ].join('\n'),
        deliverables: [
          {
            stepId: 'risk_detect',
            name: 'Risk detection',
            status: 'completed',
            output: { risks: [{ level: 'high' }, { level: 'medium' }] }
          }
        ]
      },
      global: { stubs: { 'el-icon': true } }
    })

    expect(wrapper.find('.report-content h1').text()).toBe('Contract review report')
    expect(wrapper.find('.risk-summary').text()).toContain('2')
    expect(wrapper.find('.markdown-table-wrap').exists()).toBe(true)
    await wrapper.find('.report-tab--risk').trigger('click')
    expect(wrapper.find('.contract-risk-panel').exists()).toBe(true)

    await wrapper.findAll('.report-tab')[2].trigger('click')
    expect(wrapper.find('.step-deliverables').text()).toContain('审查交付物')
    expect(wrapper.find('.step-deliverables').text()).toContain('Risk detection')
  })
})
