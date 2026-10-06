export const ACG_HISTORY_SOURCES = 'acg,agent,chat,legacy_agent_chat'
export const ACG_RUN_INVALIDATED_EVENT = 'acg-run-invalidated'

export const notifyAcgRunInvalidated = (runId: string): void => {
  if (typeof window === 'undefined' || !runId.trim()) return
  window.dispatchEvent(new CustomEvent(ACG_RUN_INVALIDATED_EVENT, { detail: { runId: runId.trim() } }))
}
