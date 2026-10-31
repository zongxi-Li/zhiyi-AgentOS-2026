import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DocumentConflictError,
  TextDocument,
  WorkspaceDocumentService,
  type DocumentSource
} from './documents'
import type { WorkspaceFileOpenRequest } from '@/services/api/agentos'

const request: WorkspaceFileOpenRequest = {
  missionId: 'mission',
  workspaceRoot: 'C:/ws',
  relativePath: 'src/main.py',
  name: 'main.py'
}

const source = (overrides: Partial<DocumentSource> = {}): DocumentSource & { load: ReturnType<typeof vi.fn>; save: ReturnType<typeof vi.fn> } => ({
  load: vi.fn(async () => ({ content: 'line1\nline2\nline3', version: 'v1' })),
  save: vi.fn(async () => ({ version: 'v2' })),
  ...overrides
} as any)

describe('TextDocument', () => {
  it('应用修改：版本递增、事件带 range、脏状态翻转', () => {
    const document = new TextDocument('u', 'abc\ndef')
    const events: any[] = []
    document.onDidChange(event => events.push(event))

    expect(document.applyEdits([{ from: 0, to: 3, insert: 'XYZ' }])).toBe(true)
    expect(document.getText()).toBe('XYZ\ndef')
    expect(document.version).toBe(2)
    expect(document.dirty).toBe(true)
    expect(events[0]).toMatchObject({ version: 2, changes: [{ from: 0, to: 3, insert: 'XYZ' }] })
  })

  it('没有实际变化时不动版本；多个不重叠修改一次应用', () => {
    const document = new TextDocument('u', 'abc')
    expect(document.applyEdits([{ from: 1, to: 1, insert: '' }])).toBe(false)
    expect(document.applyEdits([{ from: 0, to: 0, insert: 'X' }, { from: 3, to: 3, insert: 'Z' }])).toBe(true)
    expect(document.getText()).toBe('XabcZ')
    expect(document.version).toBe(2)
  })

  it('行号/列号与偏移互转，越界自动收敛', () => {
    const document = new TextDocument('u', '第一行\n\nthird')
    expect(document.lineCount).toBe(3)
    expect(document.lineAt(2).text).toBe('')
    expect(document.positionAt(4)).toEqual({ line: 2, column: 1 })
    expect(document.offsetAt({ line: 2, column: 1 })).toBe(4)
    expect(document.offsetAt({ line: 99, column: 99 })).toBe(document.getText().length)
    expect(document.positionAt(9999).line).toBe(3)
  })

  it('保存后脏状态归零，重新加载会推进版本', () => {
    const document = new TextDocument('u', 'a', 'v1')
    document.applyEdits([{ from: 1, to: 1, insert: 'b' }])
    expect(document.dirty).toBe(true)
    document.markSaved('v2')
    expect(document.dirty).toBe(false)
    expect(document.versionToken).toBe('v2')

    const version = document.version
    document.reset('fresh', 'v3')
    expect(document.getText()).toBe('fresh')
    expect(document.version).toBe(version + 1)
    expect(document.dirty).toBe(false)
  })
})

describe('WorkspaceDocumentService', () => {
  let dataSource: ReturnType<typeof source>
  let service: WorkspaceDocumentService

  beforeEach(() => {
    dataSource = source()
    service = new WorkspaceDocumentService(dataSource)
  })

  it('同一文件只读一次磁盘，重复打开复用实例', async () => {
    const first = await service.open(request)
    const second = await service.open(request)
    expect(second).toBe(first)
    expect(dataSource.load).toHaveBeenCalledTimes(1)
  })

  it('重新读取刷新内容并保留文档实例', async () => {
    const document = await service.open(request)
    document.applyEdits([{ from: 0, to: 0, insert: 'x' }])
    const reloaded = await service.reload(request)
    expect(reloaded).toBe(document)
    expect(reloaded.getText()).toBe('line1\nline2\nline3')
    expect(reloaded.dirty).toBe(false)
    expect(dataSource.load).toHaveBeenCalledTimes(2)
  })

  it('保存带上观察到的版本令牌，成功后更新基线', async () => {
    const document = await service.open(request)
    document.applyEdits([{ from: 0, to: 0, insert: '#' }])
    await service.save(document)
    expect(dataSource.save).toHaveBeenCalledWith(request, '#line1\nline2\nline3', 'v1')
    expect(document.versionToken).toBe('v2')
    expect(document.dirty).toBe(false)
  })

  it('冲突抛 DocumentConflictError 且保留草稿', async () => {
    dataSource.save.mockRejectedValueOnce({ response: { status: 409 } })
    const document = await service.open(request)
    document.applyEdits([{ from: 0, to: 0, insert: '#' }])
    await expect(service.save(document)).rejects.toBeInstanceOf(DocumentConflictError)
    expect(document.dirty).toBe(true)
    expect(document.getText()).toBe('#line1\nline2\nline3')
  })

  it('没有版本令牌的文件拒绝保存', async () => {
    dataSource.load.mockResolvedValueOnce({ content: 'legacy', version: null })
    const document = await service.open(request)
    await expect(service.save(document)).rejects.toThrow(/不支持版本保护保存/)
    expect(dataSource.save).not.toHaveBeenCalled()
  })
})
