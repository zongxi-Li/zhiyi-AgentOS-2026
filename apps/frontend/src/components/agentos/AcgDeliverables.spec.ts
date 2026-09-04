import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AcgDeliverables from './AcgDeliverables.vue'

describe('AcgDeliverables', () => {
  it('renders Markdown tables in final reports', () => {
    const wrapper = mount(AcgDeliverables, {
      props: {
        finalReport: [
          '| Risk ID | Recommendation | Accepted |',
          '| --- | --- | --- |',
          '| risk-001 | Reduce the advance payment ratio. | Yes |'
        ].join('\n'),
        deliverables: [{ stepId: 'report_generate', name: 'Report', status: 'completed', output: {} }]
      },
      global: {
        stubs: { 'el-icon': true }
      }
    })

    expect(wrapper.find('.markdown-table-wrap').exists()).toBe(true)
    expect(wrapper.findAll('th').map(cell => cell.text())).toEqual(['Risk ID', 'Recommendation', 'Accepted'])
    expect(wrapper.findAll('td').map(cell => cell.text())).toEqual(['risk-001', 'Reduce the advance payment ratio.', 'Yes'])
  })
})
