import { workflowApi, type AsyncWorkflowStartRequest } from '@/services/api/workflow'
import { launchMission, type MissionLaunchOptions, type MissionLaunchResult } from './launch'

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
export const createLaunchRequestId = () => globalThis.crypto?.randomUUID?.()
  || `launch-${Date.now()}-${Math.random().toString(36).slice(2)}`

interface Snapshot {
  signature: string
  request: AsyncWorkflowStartRequest
  materialState: 'ready' | 'pending' | 'uncertain'
}

// A cache of one submission and its retry identity, not Mission/Run state.
// Storage is optional: Conversation uses sessionStorage; Composer keeps its
// existing component-lifetime cache. Never retries any side effect on its own.
export function createMissionLaunchAttempt(cache?: { storage: Storage; key: string }) {
  let snapshot: Snapshot | null = null
  let inFlight: Promise<MissionLaunchResult> | null = null
  if (cache) {
    const saved = cache.storage.getItem(cache.key)
    if (saved) {
      try {
        snapshot = JSON.parse(saved)
        if (!snapshot?.request?.clientRequestId || typeof snapshot.signature !== 'string'
          || !['ready', 'pending', 'uncertain'].includes(snapshot.materialState)) throw new Error('invalid launch snapshot')
      } catch { throw new Error('任务启动重试记录损坏，请明确发起新任务。') }
    }
  }
  const save = () => { if (cache && snapshot) cache.storage.setItem(cache.key, JSON.stringify(snapshot)) }
  const clear = () => { if (cache) cache.storage.removeItem(cache.key); snapshot = null }

  const launch = (request: AsyncWorkflowStartRequest, options?: MissionLaunchOptions): Promise<MissionLaunchResult> => {
    if (inFlight) return inFlight
    const execute = async () => {
      if (options?.signal?.aborted) throw new DOMException('Mission launch aborted', 'AbortError')
      const signature = JSON.stringify(request)
      // Conversation's explicit operation ID freezes the original context too:
      // incoming chat messages/settings must not change an unknown submission.
      const sameOperation = request.clientRequestId
        ? snapshot?.request.clientRequestId === request.clientRequestId
        : snapshot?.signature === signature
      if (!sameOperation) {
        const captured = clone(request)
        captured.clientRequestId ||= createLaunchRequestId()
        snapshot = { signature, request: captured, materialState: 'pending' }
        save()
      }
      const current = snapshot!
      current.request.clientRequestId ||= createLaunchRequestId()
      if (current.materialState === 'uncertain') throw new Error('Material 创建结果未确认，已保留原启动身份；请核对材料结果后再发起新任务。')
      if (current.materialState === 'pending') {
        const material = current.request.input?.materialText
        if (typeof material === 'string' && material.trim()) {
          // Persist before the side effect. A lost upload response must not
          // silently create another Material on the next click/remount.
          current.materialState = 'uncertain'
          save()
          const manifest = await workflowApi.createMaterial(material.trim(), 'text/plain')
          current.request.materialRefs = [...(current.request.materialRefs || []), manifest.manifestId]
          delete current.request.input!.materialText
        }
        current.materialState = 'ready'
        save()
      }
      if (options?.signal?.aborted) throw new DOMException('Mission launch aborted', 'AbortError')
      try {
        const result = await launchMission(clone(current.request), options)
        clear()
        return result
      } catch (error) {
        if ((error as { response?: { status?: number } })?.response?.status === 409) {
          if (request.clientRequestId) clear()
          else { current.request.clientRequestId = ''; save() }
        }
        throw error
      }
    }
    // Defer execution until inFlight is set, including synchronous preparation.
    inFlight = Promise.resolve().then(execute).finally(() => { inFlight = null })
    return inFlight
  }
  return { launch }
}
