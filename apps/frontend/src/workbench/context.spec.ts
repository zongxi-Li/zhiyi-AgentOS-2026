import { describe, expect, it } from 'vitest'
import { createWorkbenchContext } from './context'

describe('createWorkbenchContext', () => {
  it('normalizes selection state without copying runtime entities into a store', () => {
    const diagnostics = [{ code: 'PLAN_SNAPSHOT_UNRESOLVED', message: '不可确定', severity: 'warning' as const }]
    const context = createWorkbenchContext({ missionId: 'mission_1', diagnostics })

    expect(context).toEqual({
      missionId: 'mission_1',
      runId: null,
      selectedSemanticTaskKey: null,
      selectedArtifactId: null,
      selectedAcgNodeId: null,
      activeEditorId: null,
      activeEntryKind: null,
      historicalMode: false,
      diagnostics,
      runtimeObservation: null
    })
  })
})
