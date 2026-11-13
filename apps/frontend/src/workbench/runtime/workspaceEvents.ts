import { apiUrl, localFetch } from '@/platform'
import { readSseFrames } from '@/utils/sse'

/** One Mission subscription; reconnect handshake supplies the durable watermark. */
export class WorkspaceProjectionClient {
  private controller: AbortController | null = null
  private retry: ReturnType<typeof setTimeout> | null = null
  private generation = 0
  private delay = 1000

  connect(missionId: string, onRevision: (revision: number) => void) {
    this.disconnect()
    const generation = this.generation
    const open = async () => {
      if (generation !== this.generation) return
      const controller = new AbortController()
      this.controller = controller
      let idle: ReturnType<typeof setTimeout> | undefined
      const touch = () => { clearTimeout(idle); idle = setTimeout(() => controller.abort(), 45000) }
      try {
        touch()
        const response = await localFetch(apiUrl(`/api/agentos/v2/missions/${encodeURIComponent(missionId)}/workspace/events`), {
          headers: { Accept: 'text/event-stream' }, cache: 'no-store', signal: controller.signal
        })
        if (generation !== this.generation || controller.signal.aborted) return
        if ([401, 403, 404].includes(response.status)) { this.disconnect(); return }
        if (!response.ok || !response.body) throw new Error('Workspace stream unavailable')
        for await (const { data } of readSseFrames(response.body, { signal: controller.signal, onActivity: touch })) {
          if (generation !== this.generation || controller.signal.aborted) return
          let event
          try { event = JSON.parse(data) }
          catch { continue /* A malformed frame cannot invalidate the current document. */ }
          if (event?.eventType === 'workspace.projection.updated' && event.schemaVersion === 1
            && event.missionId === missionId && Number.isSafeInteger(event.projectionRevision) && event.projectionRevision >= 0) {
            this.delay = 1000
            onRevision(event.projectionRevision)
          }
        }
      } catch { /* Reconnect and recover the watermark, without replaying commands. */ }
      finally {
        clearTimeout(idle)
        if (generation === this.generation) {
          this.retry = setTimeout(() => { this.retry = null; void open() }, this.delay)
          this.delay = Math.min(this.delay * 2, 15000)
        }
      }
    }
    void open()
  }

  disconnect() {
    this.generation++
    this.controller?.abort()
    this.controller = null
    if (this.retry !== null) clearTimeout(this.retry)
    this.retry = null
    this.delay = 1000
  }
}
