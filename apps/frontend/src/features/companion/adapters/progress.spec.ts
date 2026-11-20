import { afterEach, describe, expect, it } from 'vitest'
import { companionRuntimeBridge } from '../runtimeBridge'
import type { MissionWorkspaceProjection } from '@/services/api/agentos'
import { WorkflowProgressPort } from './progress'

describe('verified progress selection', () => {
  const owner = Symbol('progress-workspace')
  afterEach(() => {
    companionRuntimeBridge.release(owner)
    localStorage.clear()
    window.history.replaceState(null, '', '/')
  })
  it('ignores stale storage and unverified route IDs', () => {
    localStorage.setItem('companion.active_run_id.v1', 'stale')
    expect(new WorkflowProgressPort().resolveRunId()).toBeNull()
    window.history.replaceState(null, '', '/agentos/missions/m/workspace?runId=unverified')
    expect(new WorkflowProgressPort().resolveRunId()).toBeNull()
  })
  it('uses the verified workspace run and clears immediately while switching or leaving', () => {
    window.history.replaceState(null, '', '/agentos/missions/m/workspace?runId=stale')
    const projection = { mission: { missionId: 'm' }, activeRun: { runId: 'verified', status: 'running' },
      runs: [{ runId: 'verified', status: 'running' }] } as MissionWorkspaceProjection
    companionRuntimeBridge.activate(owner)
    companionRuntimeBridge.selectVerified(owner, projection, 'm', 'verified')
    expect(new WorkflowProgressPort().resolveRunId()).toBe('verified')
    companionRuntimeBridge.clear(owner)
    expect(new WorkflowProgressPort().resolveRunId()).toBeNull()
  })
})
