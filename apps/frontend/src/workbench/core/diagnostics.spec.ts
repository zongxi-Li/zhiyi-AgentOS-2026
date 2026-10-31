import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { workspaceDiagnostics } from './diagnostics'
import { runWorkspaceDiagnostics } from '@/services/workspaceDiagnostics'

vi.mock('@/services/workspaceDiagnostics', () => ({ runWorkspaceDiagnostics: vi.fn() }))

const resultOf = (paths: string[]) => ({
  diagnostics: paths.map((path, index) => ({
    path, line: index + 1, column: 1, severity: 'error' as const, message: 'boom', source: 'tsc', code: 'TS1'
  })),
  engine: 'tsc' as const,
  durationMs: 5,
  truncated: false,
  message: 'ok'
})

beforeEach(() => {
  workspaceDiagnostics.reset()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

it('run 写入结果并暴露数量与根目录', async () => {
  vi.mocked(runWorkspaceDiagnostics).mockResolvedValue(resultOf(['a.ts', 'b.ts']))
  await workspaceDiagnostics.run('C:/ws')
  expect(workspaceDiagnostics.count.value).toBe(2)
  expect(workspaceDiagnostics.root.value).toBe('C:/ws')
  expect(workspaceDiagnostics.error.value).toBe('')
})

it('并发检查只保留最后一次结果', async () => {
  let resolveFirst: (value: any) => void = () => {}
  const first = new Promise(resolve => { resolveFirst = resolve })
  vi.mocked(runWorkspaceDiagnostics)
    .mockReturnValueOnce(first as any)
    .mockResolvedValueOnce(resultOf(['second.ts']))

  const running = workspaceDiagnostics.run('C:/ws')
  const second = workspaceDiagnostics.run('C:/ws')
  resolveFirst(resultOf(['first.ts']))
  await Promise.all([running, second])

  expect(workspaceDiagnostics.result.value?.diagnostics.map(item => item.path)).toEqual(['second.ts'])
})

it('失败时记录错误并保留上一次结果', async () => {
  vi.mocked(runWorkspaceDiagnostics).mockResolvedValueOnce(resultOf(['a.ts']))
  await workspaceDiagnostics.run('C:/ws')
  vi.mocked(runWorkspaceDiagnostics).mockRejectedValueOnce(new Error('检查器不可用'))
  await workspaceDiagnostics.run('C:/ws')
  expect(workspaceDiagnostics.error.value).toBe('检查器不可用')
  expect(workspaceDiagnostics.count.value).toBe(1)
})

it('schedule 防抖，且确认为「没有检查器」的根目录不再自动探测', async () => {
  vi.useFakeTimers()
  vi.mocked(runWorkspaceDiagnostics).mockResolvedValue(resultOf(['a.ts']))
  workspaceDiagnostics.schedule('C:/ws', 100)
  workspaceDiagnostics.schedule('C:/ws', 100)
  await vi.advanceTimersByTimeAsync(150)
  expect(runWorkspaceDiagnostics).toHaveBeenCalledTimes(1)

  vi.mocked(runWorkspaceDiagnostics).mockResolvedValue({ ...resultOf([]), engine: 'none' })
  await workspaceDiagnostics.run('C:/ws')
  workspaceDiagnostics.schedule('C:/ws', 100)
  await vi.advanceTimersByTimeAsync(150)
  expect(runWorkspaceDiagnostics).toHaveBeenCalledTimes(2)
})

it('clear 清空结果与运行态', async () => {
  vi.mocked(runWorkspaceDiagnostics).mockResolvedValue(resultOf(['a.ts']))
  await workspaceDiagnostics.run('C:/ws')
  workspaceDiagnostics.clear()
  expect(workspaceDiagnostics.count.value).toBe(0)
  expect(workspaceDiagnostics.result.value).toBeNull()
})
