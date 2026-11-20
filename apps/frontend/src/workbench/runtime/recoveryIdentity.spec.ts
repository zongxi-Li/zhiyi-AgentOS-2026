import { beforeEach, expect, it, vi } from 'vitest'
import type { WorkflowRun } from '@/services/api/agentos'
import { beginRunRecovery, completeRunRecovery, confirmCurrentRunRecovery, pendingRunRecovery } from './recoveryIdentity'
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); localStorage.setItem('userId', 'local-owner') })
const retry = (mode = 'successor_run') => ({ kind: 'retry', stepId: 'step', payload: { mode, clientRequestId: 'same-id', expectedRuntimeRevision: 4 } } as any)
it('accepts an explicit current_run identity and rejects unknown or omitted modes', () => {
  const current = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
  expect(pendingRunRecovery('m', 'a', sessionStorage)).toEqual(current)
  expect(() => beginRunRecovery('m', 'a', retry('successor_run'), sessionStorage)).toThrow('原恢复结果未确认')
  completeRunRecovery(current, sessionStorage)
  for (const mode of ['unknown', '']) expect(() => beginRunRecovery('m', 'a', retry(mode), sessionStorage)).toThrow('身份损坏')
  expect(sessionStorage.length).toBe(0)
})
it.each(['successor_run', 'current_run'])('retains exact %s identity and fingerprint across lost responses and reloads', mode => {
  const first = beginRunRecovery('m', 'a', retry(mode), sessionStorage)
  expect(pendingRunRecovery('m', 'a', sessionStorage)).toEqual(first)
  expect(beginRunRecovery('m', 'a', retry(mode), sessionStorage)).toEqual(first)
  expect(() => beginRunRecovery('m', 'a', { ...retry(mode), payload: { ...retry(mode).payload, clientRequestId: 'new-id' } }, sessionStorage)).toThrow('原恢复结果未确认')
  completeRunRecovery(first, sessionStorage); expect(pendingRunRecovery('m', 'a', sessionStorage)).toBeNull()
})
it('fails closed for corrupt payload and account changes', () => {
  localStorage.setItem('userId', 'alice')
  beginRunRecovery('m', 'a', retry(), sessionStorage)
  localStorage.setItem('userId', 'bob'); expect(pendingRunRecovery('m', 'a', sessionStorage)).toBeNull()
  localStorage.setItem('userId', 'alice')
  const key = sessionStorage.key(0)!
  const value = JSON.parse(sessionStorage.getItem(key)!); value.payload.expectedRuntimeRevision++
  sessionStorage.setItem(key, JSON.stringify(value))
  expect(() => pendingRunRecovery('m', 'a', sessionStorage)).toThrow('身份损坏')
})

const run = (overrides: Partial<WorkflowRun> = {}): WorkflowRun => ({
  runId: 'a', missionId: 'm', workflowId: 'workflow', domain: 'general',
  status: 'retrying', runtimeRevision: 4, steps: [{ stepId: 'step', name: 'read', agentName: 'native', status: 'pending' }],
  ...overrides
})
it.each(['pending', 'retrying', 'running', 'waiting_review', 'completed', 'skipped_by_condition'] as const)(
  'confirms same-revision async admission from the target step becoming %s', async status => {
    const identity = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
    const current = run({ steps: [{ ...run().steps[0], status }] })
    const read = vi.fn().mockResolvedValue(current)
    expect(await confirmCurrentRunRecovery(identity, run(), read)).toBe(current)
    expect(read).toHaveBeenCalledWith('a')
  })
it('accepts an advanced response without requiring an extra execution read', async () => {
  const identity = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
  const current = run({ status: 'running', runtimeRevision: 5 })
  const read = vi.fn()
  expect(await confirmCurrentRunRecovery(identity, current, read)).toBe(current)
  expect(read).not.toHaveBeenCalled()
})
it.each(['failed', 'cancelled'] as const)('confirms an admitted attempt that quickly becomes %s at a newer revision', async status => {
  const identity = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
  const current = run({ status, runtimeRevision: 5, steps: [{ ...run().steps[0], status }] })
  expect(await confirmCurrentRunRecovery(identity, run(), vi.fn().mockResolvedValue(current))).toBe(current)
})
it.each([
  { missionId: 'other' }, { runId: 'other' }, { runtimeRevision: 3 }, { runtimeRevision: 4.5 }, { runtimeRevision: undefined }
])('rejects an invalid POST snapshot before reading any later Run: %j', async damage => {
  const identity = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
  const read = vi.fn().mockResolvedValue(run({ runtimeRevision: 5 }))
  await expect(confirmCurrentRunRecovery(identity, run(damage), read)).rejects.toThrow('身份或版本不匹配')
  expect(read).not.toHaveBeenCalled()
  expect(pendingRunRecovery('m', 'a', sessionStorage)).toEqual(identity)
})
it.each([
  { missionId: 'other' }, { runId: 'other' }, { runtimeRevision: 3 }, { runtimeRevision: undefined },
  { steps: [] }, { status: 'failed', steps: [{ ...run().steps[0], status: 'failed' }] }
] as Partial<WorkflowRun>[])('keeps the original operation when the reread does not confirm recovery: %j', async damage => {
  const identity = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
  await expect(confirmCurrentRunRecovery(identity, run(), vi.fn().mockResolvedValue(run(damage)))).rejects.toThrow('保留原操作')
  expect(pendingRunRecovery('m', 'a', sessionStorage)).toEqual(identity)
})
it('keeps the same client request identity after a failed confirmation read', async () => {
  const identity = beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)
  const disconnected = new Error('disconnected')
  await expect(confirmCurrentRunRecovery(identity, run(), vi.fn().mockRejectedValue(disconnected))).rejects.toBe(disconnected)
  expect(beginRunRecovery('m', 'a', retry('current_run'), sessionStorage)).toEqual(identity)
})
