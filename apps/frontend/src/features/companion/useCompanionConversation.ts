import { ref } from 'vue'
import { CompanionService, createDefaultPorts } from './companionService'
import { LocalChatPort } from './dialogue'
import type { ChatPort, CompanionMessage, CompanionPorts, CompanionState, CompanionTurn, TaskIntentCard } from './types'

interface ConversationOptions {
  persona(): { name: string; lines: string[] }
  createPorts?: () => CompanionPorts
  onReply(text: string): void
  onState(state: CompanionState): void
  onTurn(turn: CompanionTurn): void
}

/** Owns a single active turn, bounded visible history and model/local fallback. */
export function useCompanionConversation(options: ConversationOptions) {
  const messages = ref<CompanionMessage[]>([])
  const pending = ref(false)
  const card = ref<TaskIntentCard | null>(null)
  let model: ChatPort | null = null
  let controller: AbortController | null = null
  let disposed = false
  let seq = 0

  const pushMessage = (role: CompanionMessage['role'], content: string) => {
    if (disposed) return
    messages.value = [...messages.value, { id: `companion-${++seq}`, role, content, createdAt: Date.now() }].slice(-60)
  }

  const send = async (raw: string): Promise<void> => {
    const text = raw.trim()
    if (!text || pending.value || disposed) return
    const persona = options.persona()
    const ports = options.createPorts?.() ?? createDefaultPorts(persona.lines)
    const primary = model ?? ports.chat
    ports.chat = {
      async reply(value, context, signal) {
        try { return await primary.reply(value, context, signal) }
        catch (error) {
          if (signal?.aborted || (error as { name?: string })?.name === 'AbortError') throw error
          return new LocalChatPort(persona.lines).reply(value, context)
        }
      }
    }
    const active = new AbortController()
    controller = active
    pushMessage('user', text)
    pending.value = true
    options.onState('thinking')
    try {
      const turn = await new CompanionService(ports).handle(text, {
        messages: messages.value, personaName: persona.name, personaLines: persona.lines, progress: null
      }, active.signal)
      if (disposed || active.signal.aborted) return
      pushMessage('companion', turn.reply)
      card.value = turn.card
      options.onState(turn.state)
      options.onReply(turn.reply)
      options.onTurn(turn)
    } catch (error) {
      if (disposed || active.signal.aborted || (error as { name?: string })?.name === 'AbortError') return
      const reply = '刚才没能拿到回复，稍后再问我一次吧。'
      pushMessage('companion', reply)
      options.onState('error')
      options.onReply(reply)
    } finally {
      if (controller === active) { controller = null; pending.value = false }
    }
  }

  const enableModelReplies = async () => {
    if (disposed || model) return
    try {
      const { StreamChatPort } = await import('./adapters/chatStream')
      if (!disposed) model = new StreamChatPort()
    } catch { /* Local reply port remains available. */ }
  }

  const dispose = () => { disposed = true; controller?.abort(); controller = null; pending.value = false }
  return { messages, pending, card, pushMessage, send, enableModelReplies, dispose }
}
