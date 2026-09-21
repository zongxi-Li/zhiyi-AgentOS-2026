import { describe, expect, it } from 'vitest'
import { plainMissionTitle } from './missionTitle'

describe('plainMissionTitle', () => {
  it('strips leading heading markers from an objective first line', () => {
    expect(plainMissionTitle('# 任务：IC-200 智能装配生产线立项实施方案')).toBe('任务：IC-200 智能装配生产线立项实施方案')
  })

  it('strips inline heading markers from a single-line concatenated objective', () => {
    const raw = '# 任务：IC-200智能装配生产线立项实施方案 ## 一、任务背景与已知材料 一、企业与项目背景 华东某中型企业'
    expect(plainMissionTitle(raw)).toBe('任务：IC-200智能装配生产线立项实施方案 一、任务背景与已知材料 一、企业与项目背景 华东某中型企业')
  })

  it('removes emphasis markers and inline code ticks but keeps their text', () => {
    expect(plainMissionTitle('设计**高可用**的 `line-height` 方案')).toBe('设计高可用的 line-height 方案')
  })

  it('keeps link and image labels only', () => {
    expect(plainMissionTitle('参考 [架构文档](https://example.com/a) 与 ![图](https://example.com/x.png)')).toBe('参考 架构文档 与 图')
  })

  it('drops fenced code blocks entirely', () => {
    expect(plainMissionTitle('# 方案\n```sql\nSELECT 1\n```')).toBe('方案')
  })

  it('collapses whitespace and falls back when empty', () => {
    expect(plainMissionTitle('  ###\n\n')).toBe('未命名工程')
    expect(plainMissionTitle('', 'AI Mission')).toBe('AI Mission')
    expect(plainMissionTitle(null)).toBe('未命名工程')
  })
})
