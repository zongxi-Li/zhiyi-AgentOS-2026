// Display predicates concern Run status only, never lifecyclePhase or Formal Control.
export const ACTIVE_RUN_STATUSES = ['pending', 'planning', 'running', 'waiting_review', 'retrying'] as const
export const isActiveRunStatus = (status?: string | null) => ACTIVE_RUN_STATUSES.some(value => value === status)
export const isTerminalRunStatus = (status?: string | null) =>
  ['failed', 'completed', 'succeeded', 'cancelled', 'superseded'].includes(status || '')
export const isSuccessfulRunStatus = (status?: string | null) => status === 'completed' || status === 'succeeded'

export const contextQuery = <T extends Record<string, unknown>>(query: T, contextId: string) => ({ ...query, contextId })

export interface SessionBinding {
  conversationId: string
  conversationAliases?: string[]
  missionId: string
  runId: string
  status: string
  createdAt: string
  invalidAt?: string
}
export const belongsToConversation = (binding: Pick<SessionBinding, 'conversationId' | 'conversationAliases'>, key: string) =>
  binding.conversationId === key || Boolean(binding.conversationAliases?.includes(key))

export const conversationBindings = <T extends SessionBinding>(index: Record<string, T[]>, key: string): T[] =>
  [...new Map(Object.values(index).flat().filter(item => belongsToConversation(item, key))
    .map(item => [item.runId, item])).values()].sort((a, b) => a.createdAt.localeCompare(b.createdAt))

// Caller supplies proof from the in-flight first chat send, never from a persisted draft key alone.
export const mergeDraftBindings = <T extends SessionBinding>(index: Record<string, T[]>, draft: string, contextId: string) => {
  if (!draft.startsWith('draft:') || !contextId || contextId.startsWith('draft:')) return index
  const source = index[draft]
  if (!source?.length) return index
  if (source.some(item => (index[contextId] || []).some(existing =>
    existing.runId === item.runId && existing.missionId !== item.missionId))) return index
  const merged = new Map<string, T>()
  for (const item of [...source, ...(index[contextId] || [])]) {
    const previous = merged.get(item.runId)
    merged.set(item.runId, {
      ...item, conversationId: contextId,
      conversationAliases: [...new Set([draft, ...(previous?.conversationAliases || []), ...(item.conversationAliases || [])])]
    })
  }
  const next = { ...index, [contextId]: [...merged.values()].sort((a, b) => a.createdAt.localeCompare(b.createdAt)) }
  delete next[draft]
  return next
}

export interface VerifiedSessionRun { runId: string; missionId: string; status: string }
export const runMatchesSelection = (run: VerifiedSessionRun, runId: string, missionId?: string) =>
  run.runId === runId && Boolean(run.missionId) && (!missionId || run.missionId === missionId)

// Inputs are already verified against the backend. Explicit selection never falls back on failure.
export const selectSessionRun = <T extends VerifiedSessionRun>(options: {
  explicitRunId?: string; explicitMissionId?: string; verified: T[]; selectedRunId?: string;
  bindings: SessionBinding[]; historicalRunId?: string
}): T | undefined => {
  const find = (id?: string) => options.verified.find(run => id && runMatchesSelection(run, id, options.explicitMissionId))
  if (options.explicitRunId) return find(options.explicitRunId)
  const selected = find(options.selectedRunId)
  if (selected) return selected
  for (const binding of [...options.bindings].reverse()) {
    const run = find(binding.runId)
    if (!binding.invalidAt && run?.missionId === binding.missionId && isActiveRunStatus(run.status)) return run
  }
  return find(options.historicalRunId)
}
