import type { MissionWorkspaceProjection } from '@/services/api/agentos'
import type { RuntimeEvent } from '@/workbench/runtime/runtimeEvents'

export interface CompanionRunSelection { missionId: string; runId: string; status: string }

/** In-memory display bridge. Only a verified, currently visible workspace owns selection. */
export class CompanionRuntimeBridge {
  private owner: symbol | null = null
  private selected: CompanionRunSelection | null = null
  private selections = new Set<(selection: CompanionRunSelection | null) => void>()
  private events = new Set<(event: RuntimeEvent) => void>()
  get selection(): CompanionRunSelection | null { return this.selected ? { ...this.selected } : null }

  activate(owner: symbol): void {
    if (this.owner === owner) return
    this.owner = owner
    this.setSelection(null)
  }
  selectVerified(owner: symbol, projection: MissionWorkspaceProjection, missionId: string, runId?: string | null): void {
    if (owner !== this.owner) return
    const active = projection.activeRun
    if (projection.mission?.missionId !== missionId || !active?.runId
      || (runId && active.runId !== runId) || !projection.runs?.some(run => run.runId === active.runId)) {
      this.clear(owner)
      return
    }
    this.setSelection({ missionId, runId: active.runId, status: active.status })
  }
  clear(owner: symbol): void { if (owner === this.owner) this.setSelection(null) }
  release(owner: symbol): void {
    if (owner !== this.owner) return
    this.setSelection(null)
    this.owner = null
  }
  subscribeSelection(callback: (selection: CompanionRunSelection | null) => void): () => void {
    this.selections.add(callback)
    callback(this.selection)
    return () => this.selections.delete(callback)
  }
  subscribeEvents(callback: (event: RuntimeEvent) => void): () => void {
    this.events.add(callback)
    return () => this.events.delete(callback)
  }
  publishAccepted(event: RuntimeEvent): void {
    if (!this.selected || event.runId !== this.selected.runId || event.eventType === 'runtime.display.snapshot') return
    for (const callback of this.events) callback(event)
  }
  private setSelection(selection: CompanionRunSelection | null) {
    if (JSON.stringify(selection) === JSON.stringify(this.selected)) return
    this.selected = selection
    for (const callback of this.selections) callback(this.selection)
  }
}
export const companionRuntimeBridge = new CompanionRuntimeBridge()
