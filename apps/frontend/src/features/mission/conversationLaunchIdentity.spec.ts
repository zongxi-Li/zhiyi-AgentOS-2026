import { beforeEach, describe, expect, it } from 'vitest'
import { clearConversationLaunchIdentity, conversationLaunchRequestId } from './conversationLaunchIdentity'

describe('Conversation launch identity compatibility', () => {
  beforeEach(() => sessionStorage.clear())
  it('restores the existing legacy pending identity without changing or deleting other sessions', () => {
    sessionStorage.setItem('chat.workflow_submission.conversation', JSON.stringify({ conversationId: 'conversation', text: '目标', clientRequestId: 'legacy' }))
    sessionStorage.setItem('unrelated', 'preserve')
    expect(conversationLaunchRequestId(sessionStorage, 'conversation', '目标')).toBe('legacy')
    clearConversationLaunchIdentity(sessionStorage, 'conversation')
    expect(sessionStorage.getItem('unrelated')).toBe('preserve')
    expect(conversationLaunchRequestId(sessionStorage, 'conversation', '目标')).not.toBe('legacy')
  })
  it('retains the identity for a retry and creates a new identity for changed intent or Conversation', () => {
    const first = conversationLaunchRequestId(sessionStorage, 'conversation', '目标')
    expect(conversationLaunchRequestId(sessionStorage, 'conversation', '目标')).toBe(first)
    expect(conversationLaunchRequestId(sessionStorage, 'conversation', '新目标')).not.toBe(first)
    expect(conversationLaunchRequestId(sessionStorage, 'another', '目标')).not.toBe(first)
  })
})
