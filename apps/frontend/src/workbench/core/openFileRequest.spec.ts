import { afterEach, expect, it, vi } from 'vitest'
import { registerOpenFile, requestOpenFile, resetOpenFile } from './openFileRequest'

const request = {
  missionId: 'mission',
  workspaceRoot: 'C:/ws',
  relativePath: 'src/a.ts',
  name: 'a.ts'
}

afterEach(() => resetOpenFile())

it('buffers requests until a handler registers, then flushes them', () => {
  requestOpenFile(request)
  const seen: unknown[] = []
  registerOpenFile(next => seen.push(next))
  expect(seen).toEqual([request])
})

it('routes to the registered handler and clears on unregister', () => {
  const handler = vi.fn()
  const off = registerOpenFile(handler)
  requestOpenFile(request)
  expect(handler).toHaveBeenCalledWith(request)

  off()
  requestOpenFile({ ...request, relativePath: 'src/b.ts' })
  expect(handler).toHaveBeenCalledTimes(1)
})

it('ignores empty requests', () => {
  const handler = vi.fn()
  registerOpenFile(handler)
  requestOpenFile({ ...request, relativePath: '' })
  expect(handler).not.toHaveBeenCalled()
})
