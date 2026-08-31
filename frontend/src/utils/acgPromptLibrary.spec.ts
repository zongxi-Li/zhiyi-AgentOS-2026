import { describe, expect, it } from 'vitest'
import { parseAcgPromptTasks } from './acgPromptLibrary'

describe('parseAcgPromptTasks', () => {
  it('parses the structured task sections and keeps only basic fields', () => {
    const fence = '```'
    const markdown = [
      '## 工作台直接填入版（演示首选）',
      '',
      '### 任务名称',
      '',
      `${fence}text`,
      '演示任务',
      fence,
      '',
      '### 文本材料',
      '',
      `${fence}text`,
      '背景资料',
      fence,
      '',
      '### 任务目标',
      '',
      `${fence}text`,
      '完成目标',
      fence,
      '',
      '### 执行约束',
      '',
      `${fence}text`,
      '两周内完成，预算受限',
      fence,
      '',
      '### 预期交付物',
      '',
      `${fence}text`,
      '实施方案，风险清单',
      fence,
      '',
      '## 新增工作台任务（1个）',
      '',
      '### 新增任务1：第二个任务',
      '',
      '#### 任务名称',
      '',
      `${fence}text`,
      '第二个任务',
      fence,
      '',
      '#### 任务目标',
      '',
      `${fence}text`,
      '第二个目标',
      fence
    ].join('\n')

    expect(parseAcgPromptTasks(markdown)).toEqual([
      expect.objectContaining({
        group: '工作台直接填入版（演示首选）',
        name: '演示任务',
        materialText: '背景资料',
        taskGoal: '完成目标',
        constraints: ['两周内完成', '预算受限'],
        expectedArtifacts: ['实施方案', '风险清单']
      }),
      expect.objectContaining({
        group: '新增工作台任务',
        name: '第二个任务',
        taskGoal: '第二个目标'
      })
    ])
  })
})
