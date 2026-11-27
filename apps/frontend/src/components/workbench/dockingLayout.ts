import { Orientation, type DockviewApi, type SerializedDockview } from 'dockview-vue'

export const DOCK_STORAGE_KEY = 'zhiyi.mission.workspace.dockview.v1'
export const DOCK_PANELS = ['explorer', 'editor', 'inspector', 'bottom'] as const
export type DockPanelId = typeof DOCK_PANELS[number]
export const DOCK_TITLES: Record<DockPanelId, string> = {
  explorer: 'Explorer', editor: 'Editor', inspector: 'Inspector', bottom: '运行面板'
}
export interface DockLayoutState { schemaVersion: 1; layout: SerializedDockview; hidden: DockPanelId[] }
type StorageAccess = Pick<Storage, 'getItem' | 'setItem'>
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const isPanel = (value: unknown): value is DockPanelId => DOCK_PANELS.includes(value as DockPanelId)
const size = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined

/** Rebuild a layout-only allowlist. Never persist params, component state or business data. */
export function cleanDockLayout(input: unknown): SerializedDockview {
  if (!isRecord(input) || !isRecord(input.grid) || !isRecord(input.panels)) throw new Error('Invalid dock layout')
  if (input.floatingGroups && (!Array.isArray(input.floatingGroups) || input.floatingGroups.length)) throw new Error('Unsupported floating layout')
  if (input.popoutGroups && (!Array.isArray(input.popoutGroups) || input.popoutGroups.length)) throw new Error('Unsupported popout layout')
  const seen = new Set<string>()
  const groups = new Set<string>()
  let nodeCount = 0
  const walk = (value: unknown): SerializedDockview['grid']['root'] => {
    if (!isRecord(value) || ++nodeCount > 16) throw new Error('Invalid layout tree')
    const base = { size: size(value.size), ...(typeof value.visible === 'boolean' ? { visible: value.visible } : {}) }
    if (value.type === 'branch' && Array.isArray(value.data) && value.data.length > 0) {
      return { ...base, type: 'branch', data: value.data.map(walk) }
    }
    if (value.type !== 'leaf' || !isRecord(value.data)) throw new Error('Invalid group')
    const data = value.data
    if (typeof data.id !== 'string' || !data.id || groups.has(data.id) || !Array.isArray(data.views) || !data.views.length) throw new Error('Invalid group identity')
    groups.add(data.id)
    const views = data.views.map(id => {
      if (!isPanel(id) || seen.has(id)) throw new Error('Unknown or duplicate panel')
      seen.add(id)
      return id
    })
    return { ...base, type: 'leaf', data: { id: data.id, views,
      activeView: typeof data.activeView === 'string' && views.includes(data.activeView as DockPanelId) ? data.activeView : views[0] } }
  }
  const root = walk(input.grid.root)
  if (seen.size !== DOCK_PANELS.length || Object.keys(input.panels).length !== DOCK_PANELS.length) throw new Error('Missing panels')
  const panels = Object.fromEntries(DOCK_PANELS.map(id => {
    if (!isRecord(input.panels[id]) || input.panels[id].id !== id) throw new Error('Invalid panel')
    return [id, { id, contentComponent: id, title: DOCK_TITLES[id], renderer: 'always' as const }]
  }))
  if (input.grid.orientation !== 'HORIZONTAL' && input.grid.orientation !== 'VERTICAL') throw new Error('Invalid orientation')
  return { grid: { root, width: size(input.grid.width) || 1200, height: size(input.grid.height) || 800,
    orientation: input.grid.orientation === 'HORIZONTAL' ? Orientation.HORIZONTAL : Orientation.VERTICAL }, panels,
    ...(typeof input.activeGroup === 'string' && groups.has(input.activeGroup) ? { activeGroup: input.activeGroup } : {}) }
}

export function readDockLayout(storage?: StorageAccess): DockLayoutState | null {
  try {
    const raw = (storage || window.localStorage).getItem(DOCK_STORAGE_KEY)
    if (!raw || raw.length > 64000) return null
    const value: unknown = JSON.parse(raw)
    if (!isRecord(value) || value.schemaVersion !== 1 || !Array.isArray(value.hidden) || !value.hidden.every(isPanel)) return null
    return { schemaVersion: 1, layout: cleanDockLayout(value.layout), hidden: [...new Set(value.hidden)] }
  } catch { return null }
}

export function saveDockLayout(api: DockviewApi, hidden: DockPanelId[], storage?: StorageAccess): boolean {
  try {
    const value: DockLayoutState = { schemaVersion: 1, layout: cleanDockLayout(api.toJSON()), hidden: hidden.filter(isPanel) }
    ;(storage || window.localStorage).setItem(DOCK_STORAGE_KEY, JSON.stringify(value))
    return true
  } catch { return false }
}

export function createDefaultDockLayout(api: DockviewApi) {
  api.addPanel({ id: 'editor', component: 'editor', title: DOCK_TITLES.editor, renderer: 'always' })
  api.addPanel({ id: 'explorer', component: 'explorer', title: DOCK_TITLES.explorer, renderer: 'always',
    position: { referencePanel: 'editor', direction: 'left' }, initialWidth: 300 })
  api.addPanel({ id: 'inspector', component: 'inspector', title: DOCK_TITLES.inspector, renderer: 'always',
    position: { referencePanel: 'editor', direction: 'right' }, initialWidth: 320 })
  // Absolute bottom placement spans Explorer, Editor and Inspector.
  api.addPanel({ id: 'bottom', component: 'bottom', title: DOCK_TITLES.bottom, renderer: 'always',
    position: { direction: 'below' }, initialHeight: 220 })
  api.getPanel('editor')?.api.setActive()
}

/** Hide without disposing a renderer. A merged tab gets its own hidden group. */
export function setDockPanelHidden(api: DockviewApi, id: DockPanelId, hidden: boolean) {
  const panel = api.getPanel(id)
  if (!panel) return
  if (panel.api.isMaximized()) panel.api.exitMaximized()
  if (hidden && panel.group.panels.length > 1) {
    panel.api.moveTo({ group: panel.group, position: id === 'bottom' ? 'bottom' : 'right' })
  }
  panel.group.api.setVisible(!hidden)
  if (!hidden) panel.api.setActive()
}
