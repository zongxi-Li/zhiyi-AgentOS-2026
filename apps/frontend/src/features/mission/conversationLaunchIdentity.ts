import { createMissionLaunchAttempt, MissionLaunchStateError } from './launchAttempt'

// Read-only compatibility for old callers. New operation identities require an
// admitted command; legacy hints alone never authorize replacing an operation.
export function conversationLaunchRequestId(storage: Storage, conversationId: string, text: string): string {
  const pending = createMissionLaunchAttempt({ storage, slot: `conversation:${conversationId}` }).pending()
  if (pending) {
    if (pending.commandSnapshot.semantics?.objective !== text) throw new MissionLaunchStateError('BUSY', '会话已有待确认的原始操作。')
    return pending.operationId
  }
  const raw = storage.getItem(`chat.workflow_submission.${conversationId}`)
  if (raw) {
    const hint = JSON.parse(raw)
    if (hint.conversationId === conversationId && hint.text === text && typeof hint.clientRequestId === 'string' && hint.clientRequestId) return hint.clientRequestId
  }
  throw new MissionLaunchStateError('RECONCILIATION_REQUIRED', '新操作必须经 Mission Launch Authority 建立身份，不能替换旧提示。')
}

export function clearConversationLaunchIdentity(storage: Storage, conversationId: string): void {
  const attempt = createMissionLaunchAttempt({ storage, slot: `conversation:${conversationId}` })
  const pending = attempt.pending()
  if (pending?.submissionState === 'accepted') { attempt.complete(pending.operationId); return }
  if (pending || storage.getItem(`chat.workflow_submission.${conversationId}`)) {
    throw new MissionLaunchStateError('RECONCILIATION_REQUIRED', '未确认的操作身份不能清理。')
  }
}
