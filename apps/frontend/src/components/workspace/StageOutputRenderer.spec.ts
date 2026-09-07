import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StageOutputRenderer from './StageOutputRenderer.vue'

describe('StageOutputRenderer', () => {
  it('renders JSON objects as structured sections', () => {
    const wrapper = mount(StageOutputRenderer, {
      props: {
        value: JSON.stringify({
          assumptions: ['需求增长 22%'],
          constraints: [{ constraint: '项目投资不超过3500万元', mandatory: true, source: 'constraint:1' }]
        })
      }
    })

    expect(wrapper.get('[data-testid="task-stage-output"]').text()).toContain('假设')
    expect(wrapper.get('.stage-output-viewer__section-head').text()).toContain('假设 · 1')
    expect(wrapper.findAll('.stage-output-viewer__source-section').some(section => section.text().includes('约束'))).toBe(true)
    expect(wrapper.get('.stage-output-viewer__raw').element.open).toBe(false)
    expect(wrapper.text()).toContain('需求增长 22%')
    expect(wrapper.text()).toContain('项目投资不超过3500万元')
    expect(wrapper.text()).toContain('hard')
    expect(wrapper.text()).toContain('constraint:1')
    expect(wrapper.get('.stage-output-viewer__meta.is-hard').text()).toBe('hard')
    expect(wrapper.find('details').exists()).toBe(true)
  })

  it('keeps a raw JSON escape hatch', async () => {
    const wrapper = mount(StageOutputRenderer, {
      props: { value: JSON.stringify({ summary: '阶段完成' }) }
    })

    await wrapper.get('summary').trigger('click')

    expect(wrapper.get('details pre').text()).toContain('阶段完成')
    expect(wrapper.text()).toContain('STRUCTURED SOURCE')
  })

  it('falls back to plain output for non-JSON content', () => {
    const wrapper = mount(StageOutputRenderer, { props: { value: '正在生成阶段结果' } })

    expect(wrapper.get('pre').text()).toBe('正在生成阶段结果')
  })
})
