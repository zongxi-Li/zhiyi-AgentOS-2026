import { expect, it } from 'vitest'
import { readRunCapabilities } from './runCapabilities'
import { projectLifecycle } from './lifecycleProjection'
import { capabilitiesFixture } from '@/test/fixtures/runCapabilities'
import type { MissionWorkspaceProjection, WorkflowRun } from '@/services/api/agentos'

it('keeps task policy changes independent of collaboration after failure', () => {
  const failed = capabilitiesFixture('a', 'm', 'failed')
  expect(readRunCapabilities(failed, 'm', 'a', 1)?.canSetPermission).toBe(true)
  expect(readRunCapabilities(failed, 'm', 'a', 1)?.canCollaborate).toBe(false)
  const { canSetPermission: _policy, ...legacy } = failed
  expect(readRunCapabilities(legacy, 'm', 'a', 1)?.canSetPermission).toBe(false)
  const pausedFailure = capabilitiesFixture('a', 'm', 'waiting_review', 1, {
    canRecoverCurrentRun: true, retryStepId: 'reviewer',
  })
  expect(readRunCapabilities(pausedFailure, 'm', 'a', 1)?.canRecoverCurrentRun).toBe(true)
})

it('fails closed for absent, foreign, stale, malformed and unknown offers', () => {
  const cap = capabilitiesFixture('a', 'm')
  expect(readRunCapabilities(cap, 'm', 'a', 1)).toBe(cap)
  for (const value of [null, { ...cap, runId: 'b' }, { ...cap, missionId: 'foreign' },
    { ...cap, schemaVersion: 2 }, { ...cap, status: 'alien' }, { ...cap, canReview: undefined },
    { ...cap, runtimeRevision: -1 }, { ...cap, formalActions: ['invented'] }]) {
    expect(readRunCapabilities(value as any, 'm', 'a', 1)).toBeNull()
  }
  expect(readRunCapabilities(cap, 'm', 'a', 2)).toBeNull()
})
it('requires explicit matching retry mode, target and capability evidence', () => {
  const current = capabilitiesFixture('a', 'm', 'failed', 4, {
    canRecoverCurrentRun: true, retryStepId: 'node',
  })
  expect(readRunCapabilities(current, 'm', 'a', 4)?.retryMode).toBe('current_run')
  for (const patch of [{ retryMode: 'successor_run' }, { retryMode: null }, { retryStepId: null },
    { canRetrySuccessor: true }, { canRecoverCurrentRun: false }, { retryMode: undefined },
    { status: 'completed' }, { canRecoverCurrentRun: undefined }]) {
    expect(readRunCapabilities({ ...current, ...patch } as any, 'm', 'a', 4)).toBeNull()
  }
  expect(readRunCapabilities(capabilitiesFixture('a', 'm', 'failed', 4, {
    canRetrySuccessor: true, retryStepId: 'node',
  }), 'm', 'a', 4)?.retryMode).toBe('successor_run')
})
it('preserves explicit planning offers when schema-v1 recovery fields are absent', () => {
  const { canRecoverCurrentRun: _recovery, retryMode: _mode, ...legacy } = capabilitiesFixture('a', 'm', 'planning', 0, {
    canExecuteFormalAction: true, formalActions: ['materialize'],
    unavailableReasons: [{ action: 'canRecoverCurrentRun', code: 'RECOVERY_EVIDENCE_UNAVAILABLE' }],
  })
  expect(readRunCapabilities(legacy as any, 'm', 'a', 0, 'planning')).toMatchObject({
    canExecuteFormalAction: true, formalActions: ['materialize'], canCollaborate: true,
    canRecoverCurrentRun: false, retryMode: null, retryStepId: null,
  })
  for (const patch of [{ missionId: 'foreign' }, { runId: 'foreign' }, { runtimeRevision: 1 },
    { canRecoverCurrentRun: null }, { canRecoverCurrentRun: 'false' }, { retryMode: 'invented' },
    { canRetrySuccessor: true, status: 'failed', isExecutionActive: false, retryStepId: 'node' }]) {
    expect(readRunCapabilities({ ...legacy, ...patch } as any, 'm', 'a', 0, 'planning')).toBeNull()
  }
  const workspace = { mission: { missionId: 'm' }, entries: [], graphNodes: [], runs: [],
    activeRun: { runId: 'a', status: 'planning', actionCapabilities: legacy } } as unknown as MissionWorkspaceProjection
  const run = { runId: 'a', missionId: 'm', runtimeRevision: 0, status: 'planning',
    actionCapabilities: legacy, steps: [], formalControl: { status: 'PLANNING_ACCEPTED' } } as unknown as WorkflowRun
  expect(projectLifecycle({ workspace, selectedRunId: 'a', run })).toMatchObject({
    phase: 'AWAITING_CONFIRMATION', isReadOnly: false,
    capabilities: { canExecuteFormalAction: true, formalActions: ['materialize'], canRecoverCurrentRun: false },
  })
})
it('never infers recovery authority from missing schema-v1 recovery metadata', () => {
  for (const extra of [{ canRecoverCurrentRun: true, retryStepId: 'node' },
    { canRetrySuccessor: true, retryStepId: 'node' }]) {
    const { retryMode: _mode, ...withoutMode } = capabilitiesFixture('a', 'm', 'failed', 4, extra)
    expect(readRunCapabilities(withoutMode as any, 'm', 'a', 4)).toBeNull()
    const { canRecoverCurrentRun: _recovery, ...legacy } = withoutMode
    expect(readRunCapabilities(legacy as any, 'm', 'a', 4)).toBeNull()
  }
})
it('does not let selection, latest or a source edge authorize another Run', () => {
  const a = capabilitiesFixture('a', 'm', 'running', 3)
  const b = capabilitiesFixture('b', 'm', 'failed', 4)
  const workspace = { mission: { missionId: 'm' }, entries: [], graphNodes: [],
    activeRun: { runId: 'a', status: 'running', isActive: true, createdAt: '2026-01-01', actionCapabilities: a },
    runs: [{ runId: 'b', status: 'failed', isActive: false, createdAt: '2026-02-01', actionCapabilities: b }] } as MissionWorkspaceProjection
  const selected = projectLifecycle({ workspace, selectedRunId: 'a' })
  expect(selected).toMatchObject({ latestRunId: 'b', isReadOnly: false })
  expect(selected).not.toHaveProperty('currentRunId')
  expect(selected.capabilities?.canCancel).toBe(true)
  expect(projectLifecycle({ workspace, selectedRunId: 'b' }).capabilities?.canCancel).toBe(false)
  expect(projectLifecycle({ workspace, selectedRunId: 'unknown' }).isReadOnly).toBe(true)
})
it('uses the newer authoritative revision and ignores an old detailed Run', () => {
  const cap = capabilitiesFixture('a', 'm', 'cancelled', 5)
  const workspace = { mission: { missionId: 'm' }, entries: [], graphNodes: [], runs: [],
    activeRun: { runId: 'a', status: 'cancelled', actionCapabilities: cap } } as unknown as MissionWorkspaceProjection
  const old = { runId: 'a', missionId: 'm', runtimeRevision: 4, status: 'running',
    actionCapabilities: capabilitiesFixture('a', 'm', 'running', 4) } as WorkflowRun
  expect(projectLifecycle({ workspace, selectedRunId: 'a', run: old })).toMatchObject({ phase: 'CANCELLED',
    capabilities: { runtimeRevision: 5, canCancel: false }, isReadOnly: true })
})
it('does not resolve same-revision contradictory permissions with array order or timestamps', () => {
  const cap = capabilitiesFixture('a', 'm', 'running', 5)
  const workspace = { mission: { missionId: 'm' }, entries: [], graphNodes: [], runs: [],
    activeRun: { runId: 'a', status: 'running', actionCapabilities: cap } } as unknown as MissionWorkspaceProjection
  const run = { runId: 'a', missionId: 'm', runtimeRevision: 5, status: 'cancelled',
    actionCapabilities: capabilitiesFixture('a', 'm', 'cancelled', 5) } as WorkflowRun
  expect(projectLifecycle({ workspace, selectedRunId: 'a', run })).toMatchObject({
    phase: 'UNKNOWN', capabilities: null, isReadOnly: true })
})

it('allows only the offered terminal soft delete on a superseded Run', () => {
  const cap = capabilitiesFixture('a', 'm', 'superseded', 5, { lineage: { supersededByRunId: 'b' } })
  expect(readRunCapabilities(cap, 'm', 'a', 5)?.canDelete).toBe(true)
  expect(readRunCapabilities({ ...cap, canCancel: true }, 'm', 'a', 5)).toBeNull()
  expect(readRunCapabilities({ ...cap, canRerunSuccessor: true }, 'm', 'a', 5)).toBeNull()
  expect(readRunCapabilities(capabilitiesFixture('a', 'm', 'running', 5, { canDelete: true }), 'm', 'a', 5)).toBeNull()
})
