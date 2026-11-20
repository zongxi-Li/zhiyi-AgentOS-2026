import { ref } from 'vue'
import { resolveState, stateFromRuntimeEvent } from './companionState'
import { companionRuntimeBridge, type CompanionRuntimeBridge, type CompanionRunSelection } from './runtimeBridge'
import type { CompanionState } from './types'
import type { RuntimeEvent } from '@/workbench/runtime/runtimeEvents'

interface RuntimeOptions {
  bridge?: CompanionRuntimeBridge
  onChange(): void
  onNotice(event: RuntimeEvent, state: 'error' | 'alert'): void
}

function statusState(status: string): CompanionState | null {
  switch (status.toLowerCase()) {
    case 'pending': case 'queued': case 'planning': return 'thinking'
    case 'running': return 'working'
    case 'completed': case 'succeeded': return 'happy'
    case 'failed': return 'error'
    case 'waiting_review': case 'waiting_approval': case 'cancelled': case 'superseded': return 'alert'
    default: return null
  }
}

/** Persistent selected-run facts survive short-lived conversations and pet expressions. */
export function useCompanionRuntime(options: RuntimeOptions) {
  const bridge = options.bridge ?? companionRuntimeBridge
  const state = ref<CompanionState | null>(null)
  let selection: CompanionRunSelection | null = null
  let stopSelection: (() => void) | null = null
  let stopEvents: (() => void) | null = null
  const seen = new Set<string>()
  const select = (next: CompanionRunSelection | null) => {
    const changedRun = next?.runId !== selection?.runId || next?.missionId !== selection?.missionId
    if (changedRun) {
      seen.clear()
      state.value = next ? statusState(next.status) : null
    } else if (next && next.status !== selection?.status) {
      const mapped = statusState(next.status)
      if (mapped) state.value = ['completed', 'succeeded', 'failed', 'cancelled', 'superseded'].includes(next.status.toLowerCase())
        ? mapped : resolveState(state.value ?? 'idle', mapped)
    }
    selection = next
    options.onChange()
  }
  const receive = (event: RuntimeEvent) => {
    if (!selection || event.runId !== selection.runId || seen.has(event.eventId)) return
    const mapped = stateFromRuntimeEvent(event.eventType)
    if (!mapped) return
    seen.add(event.eventId)
    if (seen.size > 256) seen.delete(seen.values().next().value!)
    const definitive = ['run.completed', 'run.failed', 'run.cancelled', 'run.superseded'].includes(event.eventType)
    const approvalResolved = event.eventType === 'tool.approval_resolved' && state.value === 'alert'
    state.value = definitive || approvalResolved ? mapped : resolveState(state.value ?? 'idle', mapped)
    options.onChange()
    if (mapped === 'error' || mapped === 'alert') options.onNotice(event, mapped)
  }
  const start = () => {
    if (stopSelection) return
    stopSelection = bridge.subscribeSelection(select)
    stopEvents = bridge.subscribeEvents(receive)
  }
  const dispose = () => {
    stopSelection?.(); stopEvents?.()
    stopSelection = null; stopEvents = null
    seen.clear()
  }
  return { state, start, dispose }
}
