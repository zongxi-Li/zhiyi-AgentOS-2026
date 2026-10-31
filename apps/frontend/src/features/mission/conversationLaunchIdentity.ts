import { createLaunchRequestId } from './launchAttempt'

const keyFor = (conversationId: string) => `chat.workflow_submission.${conversationId}`

// Retain the existing sessionStorage shape/key for pending legacy submissions.
export function conversationLaunchRequestId(storage: Storage, conversationId: string, text: string): string {
  try {
    const pending = JSON.parse(storage.getItem(keyFor(conversationId)) || 'null')
    if (pending?.conversationId === conversationId && pending.text === text
      && typeof pending.clientRequestId === 'string' && pending.clientRequestId) return pending.clientRequestId
  } catch { /* Malformed legacy identity hints can be replaced before a new operation. */ }
  const clientRequestId = createLaunchRequestId()
  storage.setItem(keyFor(conversationId), JSON.stringify({ conversationId, text, clientRequestId }))
  return clientRequestId
}

export function clearConversationLaunchIdentity(storage: Storage, conversationId: string): void {
  storage.removeItem(keyFor(conversationId))
}
