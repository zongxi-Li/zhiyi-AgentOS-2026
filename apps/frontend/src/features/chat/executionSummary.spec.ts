import { describe, expect, it } from 'vitest'
import { mergeExecutionSummary, normalizeExecutionSummary, type ExecutionSummaryLike } from './executionSummary'

const approval = (status = 'pending', sessionId = 'session', approvalId = 'approval') => ({
  stage: 'tool:unknown:undefined', status: status === 'pending' ? 'approval_required' : 'running', description: 'approval event',
  approval: { approvalId, sessionId, toolCallId: 'call-1', invocationId: 'call-1', toolName: 'run_command', status }
})

describe('execution summary identity reconciliation', () => {
  it.each([false, true])('repairs nested approval snapshots without leaving pending duplicates (%s)', reverse => {
    const items = [approval(), approval('approved')]
    const before = JSON.stringify(items)
    const result = normalizeExecutionSummary(reverse ? [...items].reverse() : items)
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ stage: 'tool:run_command:call-1', status: 'running', approval: { status: 'approved' } })
    expect(JSON.stringify(items)).toBe(before)
    result[0].approval!.status = 'denied'
    expect(items[0].approval.status).toBe('pending')
  })

  it('merges the real tool result with its approval while preserving outputs and duration', () => {
    const terminal = { command: 'test', exitCode: 0, stdout: 'confirmed output', stderr: '' }
    const result = normalizeExecutionSummary<ExecutionSummaryLike>([
      approval(), approval('approved'),
      { stage: 'tool:run_command:call-1', status: 'completed', description: 'finished', durationMs: 23, terminal },
      { stage: 'tool:run_command:call-1', status: 'running', description: 'stale start' }
    ])
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ status: 'completed', description: 'finished', durationMs: 23, terminal, approval: { status: 'approved' } })
    expect(result[0].terminal).not.toBe(terminal)
  })

  it('keeps different approvals and sessions distinct when provider call IDs repeat', () => {
    const result = normalizeExecutionSummary([
      approval('approved', 'session-a', 'one'), approval('pending', 'session-b', 'one'),
      approval('pending', 'session-a', 'two'),
      { stage: 'tool:run_command:call-1', status: 'completed', description: 'unscoped result' }
    ])
    expect(result).toHaveLength(4)
    expect(result.filter(item => item.approval?.status === 'pending')).toHaveLength(2)
  })

  it('never groups unrelated fallback stages that have no real identity', () => {
    const result = normalizeExecutionSummary([
      { stage: 'tool:unknown:undefined', status: 'running', description: 'first' },
      { stage: 'tool:unknown:undefined', status: 'running', description: 'second' },
      { stage: 'tool:run_command:run_command', status: 'running', description: 'unnamed third' }
    ])
    expect(result).toHaveLength(3)
  })

  it.each(['denied', 'expired'])('does not revert an approval %s terminal to pending', status => {
    const result = mergeExecutionSummary([approval(status)], approval())
    expect(result).toHaveLength(1)
    expect(result[0].approval?.status).toBe(status)
  })

  it('retains a confirmed approval when stream shutdown later infers expiry', () => {
    expect(mergeExecutionSummary([approval('approved')], approval('expired'))[0].approval?.status).toBe('approved')
  })

  it('does not duplicate unchanged snapshots or lose independent work', () => {
    const input: ExecutionSummaryLike[] = [approval(), approval('approved'),
      { stage: 'tool:read_file:read-2', status: 'completed', description: 'read', activity: { summary: 'file read' } }]
    const once = normalizeExecutionSummary(input)
    expect(normalizeExecutionSummary([...once, ...input])).toEqual(once)
  })
})
