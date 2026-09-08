import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StageOutputRenderer from './StageOutputRenderer.vue'

describe('StageOutputRenderer', () => {
  it('renders JSON objects as structured sections', async () => {
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
    await wrapper.get('.stage-output-viewer__source > summary').trigger('click')
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

    await wrapper.get('.stage-output-viewer__source > summary').trigger('click')
    await wrapper.get('.stage-output-viewer__raw > summary').trigger('click')

    expect(wrapper.get('details pre').text()).toContain('阶段完成')
    expect(wrapper.text()).toContain('STRUCTURED SOURCE')
  })

  it('falls back to plain output for non-JSON content', () => {
    const wrapper = mount(StageOutputRenderer, { props: { value: '正在生成阶段结果' } })

    expect(wrapper.get('pre').text()).toBe('正在生成阶段结果')
  })

  it('keeps long text readable and expands nested result values structurally', () => {
    const wrapper = mount(StageOutputRenderer, {
      props: {
        value: JSON.stringify({
          solution_design: [{
            overview: '这是一个需要换行展示的方案概览。',
            phases: [{ name: '阶段一', deliverables: ['设计文档', '验收报告'] }]
          }]
        })
      }
    })

    expect(wrapper.text()).toContain('这是一个需要换行展示的方案概览。')
    expect(wrapper.text()).toContain('阶段一')
    expect(wrapper.text()).toContain('设计文档')
    expect(wrapper.findAll('.structured-value__list').length).toBeGreaterThan(0)
  })

  it('gives narrative fields a readable full-width treatment while keeping raw keys visible', () => {
    const wrapper = mount(StageOutputRenderer, {
      props: {
        value: JSON.stringify({
          architecture: {
            deployment: '企业内部部署方案：事件总线与微服务集群。'.repeat(24),
            rationale: '基于约束与审计要求形成的设计依据。'.repeat(24),
            style: '事件驱动微服务架构'
          }
        })
      }
    })

    const narrativeFields = wrapper.findAll('.stage-output-viewer__fields--record > .is-narrative')
    expect(narrativeFields).toHaveLength(2)
    expect(narrativeFields.every(field => field.classes('is-narrative'))).toBe(true)
    expect(wrapper.text()).toContain('部署方案')
    expect(wrapper.text()).toContain('deployment')
    expect(wrapper.findAll('.structured-value__text.is-long')).toHaveLength(2)
    expect(wrapper.get('.stage-output-viewer__field-label').element).toBeTruthy()
  })

  it('collapses oversized conclusions and keeps a readable preview before expansion', async () => {
    const conclusion = '指标与供应商协同规则：'.concat('每条规则都必须保留来源、阈值、权重与触发条件；'.repeat(40))
    const wrapper = mount(StageOutputRenderer, {
      props: {
        value: JSON.stringify({ solution_design: [{ overview: conclusion }] })
      }
    })

    const disclosure = wrapper.get('.structured-value__disclosure')
    expect((disclosure.element as HTMLDetailsElement).open).toBe(false)
    expect(disclosure.get('summary').text()).toContain('展开完整结论')
    expect(disclosure.get('summary').text()).toContain('字符')

    await disclosure.get('summary').trigger('click')
    expect((disclosure.element as HTMLDetailsElement).open).toBe(true)
    expect(disclosure.findAll('.structured-value__markdown p').length).toBeGreaterThan(1)
  })
})
