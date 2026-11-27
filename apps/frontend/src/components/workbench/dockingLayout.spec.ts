import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createDockview, type DockviewApi } from 'dockview-vue'
import { DOCK_PANELS, DOCK_STORAGE_KEY, cleanDockLayout, createDefaultDockLayout,
  readDockLayout, saveDockLayout, setDockPanelHidden } from './dockingLayout'

let api: DockviewApi
let host: HTMLDivElement
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  host = document.createElement('div')
  document.body.append(host)
  api = createDockview(host, { disableAutoResizing: true, disableFloatingGroups: true,
    createComponent: () => ({ element: document.createElement('div'), init() {} }) })
  api.layout(1400, 900)
  createDefaultDockLayout(api)
  localStorage.clear()
})
afterEach(() => { api.dispose(); host.remove(); vi.unstubAllGlobals() })

describe('Mission Dockview layout with the real engine', () => {
  it('creates four unique panels, three top columns and a full-width bottom', () => {
    expect(new Set(api.panels.map(panel => panel.id))).toEqual(new Set(DOCK_PANELS))
    expect(api.groups).toHaveLength(4)
    const root = api.toJSON().grid.root
    expect(root.type).toBe('branch')
    const rows = root.data as typeof root[]
    expect(rows).toHaveLength(2)
    const columns = rows[0].data as typeof root[]
    expect(columns.map(column => (column.data as { views: string[] }).views)).toEqual([['explorer'], ['editor'], ['inspector']])
    expect((rows[1].data as { views: string[] }).views).toEqual(['bottom'])
    expect(api.getPanel('bottom')!.api.width).toBe(1400)
  })

  it('moves, merges and splits panels without replacing panel identities', () => {
    const editor = api.getPanel('editor')!
    const inspector = api.getPanel('inspector')!
    inspector.api.moveTo({ group: editor.group, position: 'center' })
    expect(inspector.group).toBe(editor.group)
    expect(api.groups).toHaveLength(3)
    inspector.api.moveTo({ group: editor.group, position: 'bottom' })
    expect(inspector.group).not.toBe(editor.group)
    expect(api.groups).toHaveLength(4)
    expect(api.getPanel('inspector')).toBe(inspector)
    api.getPanel('explorer')!.api.moveTo({ group: editor.group, position: 'right' })
    const serialized = JSON.stringify(api.toJSON().grid.root)
    expect(serialized.indexOf('"editor"')).toBeLessThan(serialized.indexOf('"explorer"'))
  })

  it('hides a merged panel independently and reopens the same instance', () => {
    const inspector = api.getPanel('inspector')!
    const editor = api.getPanel('editor')!
    inspector.api.moveTo({ group: editor.group, position: 'center' })
    setDockPanelHidden(api, 'inspector', true)
    expect(inspector.api.isVisible).toBe(false)
    expect(editor.api.isVisible).toBe(true)
    setDockPanelHidden(api, 'inspector', false)
    expect(inspector.api.isVisible).toBe(true)
    expect(api.getPanel('inspector')).toBe(inspector)
  })

  it('roundtrips groups, sizes, active tab and hidden panels and reuses renderers', () => {
    const inspector = api.getPanel('inspector')!
    inspector.api.moveTo({ group: api.getPanel('editor')!.group, position: 'center' })
    inspector.api.setActive()
    setDockPanelHidden(api, 'bottom', true)
    expect(saveDockLayout(api, ['bottom'])).toBe(true)
    const saved = readDockLayout()!
    expect(saved.hidden).toEqual(['bottom'])
    expect(saved.layout.panels.inspector.params).toBeUndefined()
    api.fromJSON(saved.layout, { reuseExistingPanels: true })
    expect(api.getPanel('inspector')).toBe(inspector)
    expect(api.getPanel('inspector')!.group.activePanel?.id).toBe('inspector')
    expect(api.getPanel('bottom')!.api.isVisible).toBe(false)
  })

  it('restores defaults without replacing existing panels', () => {
    const defaults = cleanDockLayout(api.toJSON())
    const editor = api.getPanel('editor')!
    api.getPanel('inspector')!.api.moveTo({ group: editor.group, position: 'center' })
    api.fromJSON(defaults, { reuseExistingPanels: true })
    expect(api.groups).toHaveLength(4)
    expect(api.getPanel('editor')).toBe(editor)
  })

  it('keeps every panel available after hiding all regions and reopening Editor', () => {
    for (const id of DOCK_PANELS) setDockPanelHidden(api, id, true)
    expect(api.panels).toHaveLength(4)
    for (const panel of api.panels) expect(panel.api.isVisible).toBe(false)
    setDockPanelHidden(api, 'editor', false)
    expect(api.getPanel('editor')!.api.isVisible).toBe(true)
  })

  it('rejects corrupt, incompatible, duplicate and missing panel layouts', () => {
    for (const raw of ['{', JSON.stringify({ schemaVersion: 2 }), JSON.stringify({ schemaVersion: 1, hidden: [], layout: {} })]) {
      localStorage.setItem(DOCK_STORAGE_KEY, raw)
      expect(readDockLayout()).toBeNull()
    }
    const value = api.toJSON()
    delete value.panels.editor
    expect(() => cleanDockLayout(value)).toThrow()
    const valid = api.toJSON()
    const serialized = JSON.stringify(valid).replace('"explorer"]', '"editor"]')
    expect(() => cleanDockLayout(JSON.parse(serialized))).toThrow()
  })

  it('does not serialize business params or fail when storage is unavailable', () => {
    api.getPanel('editor')!.api.updateParameters({ taskId: 'secret-task', runId: 'secret-run', content: 'private body' })
    expect(saveDockLayout(api, [])).toBe(true)
    expect(localStorage.getItem(DOCK_STORAGE_KEY)).not.toContain('secret')
    expect(localStorage.getItem(DOCK_STORAGE_KEY)).not.toContain('private body')
    const denied = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') } }
    expect(readDockLayout(denied)).toBeNull()
    expect(saveDockLayout(api, [], denied)).toBe(false)
  })
})
