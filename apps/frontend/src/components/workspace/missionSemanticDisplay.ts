import type { MissionWorkspaceProjection } from '@/services/api/agentos'

// Display projections never change persisted Mission or Run state.
export const missionDisplayObjective = (projection: MissionWorkspaceProjection): string =>
  projection.missionSemanticView?.semanticStatus === 'INITIALIZED'
    ? projection.missionSemanticView.objective || '正式语义不可用'
    : projection.missionDisplay
    ? projection.missionDisplay.objective || '尚未设置正式目标'
    : projection.mission.goal || projection.mission.description || 'Mission'

export const runDisplayObjective = (projection: MissionWorkspaceProjection): string => {
  if (projection.selectedRunBasisStatus === 'BOUND' && projection.selectedRunBasis) {
    return projection.selectedRunBasis.objective
  }
  if (projection.selectedRunBasisStatus === 'BOUND') return 'Run 语义依据不可用'
  if (projection.selectedRunBasisStatus === 'UNBOUND') return '旧 Run 未绑定语义依据'
  if (projection.selectedRunBasisStatus === 'RUNTIME_UNAVAILABLE') return 'Run 语义依据不可用'
  return missionDisplayObjective(projection)
}

export const missionDisplayLabel = (projection: MissionWorkspaceProjection): string =>
  projection.missionSemanticView?.semanticStatus === 'INITIALIZED'
    ? `正式目标 · revision ${projection.missionSemanticView.missionRevision}`
    : projection.missionSemanticView
      ? '正式目标未初始化 · 兼容展示'
      : '兼容展示 · 未读取正式语义'

export const missionDocumentContent = (projection: MissionWorkspaceProjection): string =>
  projection.entries.find(entry => entry.entryId === 'overview:mission.md')?.content
    || `# ${missionDisplayObjective(projection)}\n\n${missionDisplayLabel(projection)}`
