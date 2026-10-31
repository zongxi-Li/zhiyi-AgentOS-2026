import { describe, expect, it } from 'vitest'
import { isActiveRunStatus, isTerminalRunStatus, isSuccessfulRunStatus, mergeDraftBindings, conversationBindings, selectSessionRun } from './session'

const binding = (runId: string, missionId = 'M', conversationId = 'draft:D', status = 'running') =>
  ({ runId, missionId, conversationId, status, createdAt: runId })
describe('Session association and Run resolution', () => {
  it('merges multiple Missions and Runs by Run identity, preserving historical aliases without mutation', () => {
    const original = { 'draft:D': [binding('1'), binding('2'), binding('3', 'other')], ctx: [binding('1', 'M', 'ctx')] }
    const before = JSON.stringify(original)
    const result = mergeDraftBindings(original, 'draft:D', 'ctx')
    expect(result.ctx.map(item => item.runId)).toEqual(['1', '2', '3'])
    expect(conversationBindings(result, 'draft:D')).toEqual(result.ctx)
    expect(JSON.stringify(original)).toBe(before)
    expect(mergeDraftBindings(original, 'draft:unknown', 'ctx')).toBe(original)
    const conflicting = { 'draft:D': [binding('1')], ctx: [binding('1', 'different-Mission', 'ctx')] }
    expect(mergeDraftBindings(conflicting, 'draft:D', 'ctx')).toBe(conflicting)
  })
  it.each(['failed', 'completed', 'succeeded', 'cancelled', 'superseded'])('%s is terminal', status => {
    expect(isTerminalRunStatus(status)).toBe(true)
    expect(isActiveRunStatus(status)).toBe(false)
  })
  it.each(['pending', 'planning', 'running', 'waiting_review', 'retrying'])('%s remains active', status => {
    expect(isTerminalRunStatus(status)).toBe(false)
    expect(isActiveRunStatus(status)).toBe(true)
  })
  it('maps completed and succeeded to success without treating superseded as success', () => {
    expect(isSuccessfulRunStatus('completed')).toBe(true)
    expect(isSuccessfulRunStatus('succeeded')).toBe(true)
    expect(isSuccessfulRunStatus('superseded')).toBe(false)
  })
  const verified = [{ runId: 'old', missionId: 'M', status: 'superseded' }, { runId: 'new', missionId: 'M', status: 'running' }]
  const bindings = [binding('old'), binding('new')]
  it('keeps explicit history even when the latest Run is its successor', () => {
    expect(selectSessionRun({ explicitRunId: 'old', explicitMissionId: 'M', selectedRunId: 'new', verified, bindings })?.runId).toBe('old')
  })
  it('rejects a Run belonging to another Mission without falling back', () => {
    expect(selectSessionRun({ explicitRunId: 'old', explicitMissionId: 'wrong', verified, bindings })).toBeUndefined()
  })
  it('keeps a verified selected historical Run ahead of new active bindings', () => {
    expect(selectSessionRun({ selectedRunId: 'old', verified, bindings })?.runId).toBe('old')
    expect(selectSessionRun({ verified, bindings })?.runId).toBe('new')
    expect(selectSessionRun({ verified: [verified[0]], bindings, historicalRunId: 'old' })?.runId).toBe('old')
    expect(selectSessionRun({ verified: [], bindings })).toBeUndefined()
  })
})
