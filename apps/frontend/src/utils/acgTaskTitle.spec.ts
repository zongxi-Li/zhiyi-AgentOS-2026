import { describe, expect, it } from 'vitest'
import { resolveAcgTaskTitle, resolveAcgTaskTitleAutoUpdate } from './acgTaskTitle'

describe('resolveAcgTaskTitle', () => {
  it('prefers the explicit task name stored with a new Run', () => {
    expect(resolveAcgTaskTitle({
      title: '一段很长的旧目标',
      input: { taskName: '软件开发合同审查' }
    })).toBe('软件开发合同审查')
  })

  it('converts a legacy prompt title into a concise task title', () => {
    expect(resolveAcgTaskTitle({
      title: '请以 ACG 多智能体协作方式审查这份软件开发合同，强制生成差异化任务图，并完整执行后续流程。'
    })).toBe('软件开发合同审查')
  })

  it('keeps an existing concise title unchanged', () => {
    expect(resolveAcgTaskTitle({ title: '劳动合同风险复核' })).toBe('劳动合同风险复核')
  })

  it('extracts the contract type from a legacy lawyer chat title', () => {
    expect(resolveAcgTaskTitle({
      title: 'Lawyer agent chat: 请执行合同审查工作流：软件开发合同总价80万元，约定上线后付款。'
    })).toBe('软件开发合同审查')
  })

  it('uses both parties to identify legacy task-material records', () => {
    expect(resolveAcgTaskTitle({
      title: 'Lawyer agent chat: 【任务材料】\n\n甲方：华东智造设备有限公司\n乙方：上海云策软件有限公司\n\n双方拟签署合同。'
    })).toBe('华东智造设备与上海云策软件合同审查')
  })

  it('keeps a manually entered task name when the task goal changes', () => {
    expect(resolveAcgTaskTitleAutoUpdate({
      currentTitle: 'IC-200智能装配生产线立项实施方案',
      previousAutoTitle: '',
      taskGoal: '基于任务材料，为IC-200工业控制器设计智能装配生产线。',
      defaultTitle: ''
    })).toEqual({
      title: 'IC-200智能装配生产线立项实施方案',
      autoTitle: ''
    })
  })

  it('continues updating a title while it is still auto-generated', () => {
    expect(resolveAcgTaskTitleAutoUpdate({
      currentTitle: '基于任务材料',
      previousAutoTitle: '基于任务材料',
      taskGoal: '大型综合医院智慧门诊流程与资源优化方案。',
      defaultTitle: ''
    })).toEqual({
      title: '大型综合医院智慧门诊流程与资源优化方案。',
      autoTitle: '大型综合医院智慧门诊流程与资源优化方案。'
    })
  })

  it('keeps the task name empty when the task goal is empty', () => {
    expect(resolveAcgTaskTitleAutoUpdate({
      currentTitle: '',
      previousAutoTitle: '',
      taskGoal: '   ',
      defaultTitle: ''
    })).toEqual({
      title: '',
      autoTitle: ''
    })
  })
})
