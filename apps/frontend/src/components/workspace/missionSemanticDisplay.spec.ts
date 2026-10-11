import { describe, expect, it } from 'vitest'
import type { MissionWorkspaceProjection } from '@/services/api/agentos'
import { missionDisplayObjective, missionDisplayLabel, runDisplayObjective, missionDocumentContent } from './missionSemanticDisplay'

const projection = (): MissionWorkspaceProjection => ({
  mission: { missionId: 'm', userId: 'u', goal: 'legacy goal', description: '', metadata: {},
    createdAt: '', updatedAt: '', status: 'created' },
  entries: [], runs: [], graphNodes: [], diagnostics: [],
  missionDisplay: { objective: 'current formal goal', sourceType: 'SEMANTIC' },
  missionSemanticView: { missionId: 'm', semanticStatus: 'INITIALIZED', missionRevision: 2,
    commitId: 'c2', objective: 'current formal goal', constraints: [], sourceReferences: [], sourceStatus: 'NOT_APPLICABLE' }
})

describe('Mission semantic display', () => {
  it('shows current semantics separately from selected Run history', () => {
    const value = projection()
    value.selectedRunBasisStatus = 'BOUND'
    value.selectedRunBasis = { basisSchemaVersion: 1, fingerprintVersion: 1, missionId: 'm',
      sourceType: 'SEMANTIC', sourceRevision: 1, commitId: 'c1', objective: 'historical run goal',
      constraints: [], sourceReferences: [], sourceStatus: 'NOT_APPLICABLE', fingerprint: 'abc' }
    expect(missionDisplayObjective(value)).toBe('current formal goal')
    expect(runDisplayObjective(value)).toBe('historical run goal')
    expect(missionDisplayLabel(value)).toContain('revision 2')
  })

  it('does not backfill old Runs or unavailable Run records with current goals', () => {
    const value = projection()
    value.selectedRunBasisStatus = 'UNBOUND'
    expect(runDisplayObjective(value)).toBe('旧 Run 未绑定语义依据')
    value.selectedRunBasisStatus = 'RUNTIME_UNAVAILABLE'
    expect(runDisplayObjective(value)).toBe('Run 语义依据不可用')
  })

  it('labels uninitialized compatibility without declaring a formal goal', () => {
    const value = projection()
    value.missionSemanticView = { missionId: 'm', semanticStatus: 'UNINITIALIZED', missionRevision: 0,
      constraints: [], sourceReferences: [], sourceStatus: 'NOT_APPLICABLE' }
    value.missionDisplay = { objective: 'old identity goal', sourceType: 'IDENTITY_COMPATIBILITY' }
    expect(missionDisplayObjective(value)).toBe('old identity goal')
    expect(missionDisplayLabel(value)).toContain('未初始化')
    value.missionDisplay = { sourceType: 'NONE' }
    expect(missionDisplayObjective(value)).toBe('尚未设置正式目标')
  })

  it('reuses the authoritative virtual document in breadcrumb navigation', () => {
    const value = projection()
    value.entries = [{ entryId: 'overview:mission.md', name: 'mission.md', kind: 'virtual_document',
      group: 'overview', displayOrder: 1, content: '# current\n\nRun history' }]
    expect(missionDocumentContent(value)).toBe('# current\n\nRun history')
  })

  it('labels older server payloads as compatibility display', () => {
    const value = projection()
    delete value.missionSemanticView
    delete value.missionDisplay
    expect(missionDisplayObjective(value)).toBe('legacy goal')
    expect(missionDisplayLabel(value)).toContain('未读取正式语义')
  })

  it('does not use old aliases when a formal view or bound Run payload is incomplete', () => {
    const value = projection()
    delete value.missionDisplay
    expect(missionDisplayObjective(value)).toBe('current formal goal')
    value.missionSemanticView!.objective = null
    expect(missionDisplayObjective(value)).toBe('正式语义不可用')
    value.selectedRunBasisStatus = 'BOUND'
    expect(runDisplayObjective(value)).toBe('Run 语义依据不可用')
  })
})
