import { describe, expect, it } from 'vitest'
import { streamingContent } from './streamingContent'

describe('public streaming text', () => {
  it('displays unfinished narrative strings before JSON completion', () => {
    expect(streamingContent('{"answer":"正在检查')).toBe('正在检查')
    expect(streamingContent('{"answer":"正在检查，已找到原因"}')).toBe('正在检查，已找到原因')
  })
  it('projects nested evidence and lists without printing property names or identifiers', () => {
    expect(streamingContent('{"evidence_analysis":[{"id":"internal","description":"第一项"},{"description":"第二项')).toBe('第一项\n\n第二项')
    expect(streamingContent('{"constraints":["保持数据","权限不变')).toBe('保持数据\n\n权限不变')
  })
  it('suppresses private subtrees even when their values use public field names', () => {
    const output = '{"reasoning_content":{"summary":"PRIVATE"},"authorization":[{"description":"PRIVATE"}],"answer":"可见'
    expect(streamingContent(output)).toBe('可见')
    expect(streamingContent('{"reasoning_content":"PRIVATE')).toBe('')
  })
  it('waits for incomplete escapes and decodes public unicode and newlines', () => {
    expect(streamingContent('{"content":"前缀\\u4f')).toBe('前缀')
    expect(streamingContent('{"content":"前缀\\u4f60\\n下一行\\')).toBe('前缀你\n下一行')
    expect(streamingContent('{"content":"引号\\"内容')).toBe('引号"内容')
  })
  it('supports public commentary and JSON fences while keeping previews bounded', () => {
    expect(streamingContent('我先检查目录。')).toBe('我先检查目录。')
    expect(streamingContent('```json\n{"summary":"可见')).toBe('可见')
    expect(streamingContent('a'.repeat(70000))).toHaveLength(65536)
  })
})
