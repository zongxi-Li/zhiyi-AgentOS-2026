import { onBeforeUnmount, onMounted, ref } from 'vue'

const STORAGE_KEY = 'layout.docked_workspace.geometry.v1'
const CHANGE_EVENT = 'docked-workspace-geometry-change'
export const DOCK_LEFT_DEFAULT = 320
export const DOCK_RIGHT_DEFAULT = 320

type Geometry = { leftWidth: number; rightWidth: number }

const readGeometry = (): Geometry => {
  let stored: Partial<Geometry> = {}
  try { stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {} } catch { /* Use defaults. */ }
  const width = (value: unknown, min: number, max: number, fallback: number) => (
    typeof value === 'number' && Number.isFinite(value)
      ? Math.min(max, Math.max(min, Math.round(value))) : fallback
  )
  return {
    leftWidth: width(stored.leftWidth, 240, 520, DOCK_LEFT_DEFAULT),
    rightWidth: width(stored.rightWidth, 280, 960, DOCK_RIGHT_DEFAULT)
  }
}

/** Share dock boundaries without sharing the pages' content or runtime state. */
export const useDockedWorkspaceGeometry = () => {
  const initial = readGeometry()
  const leftWidth = ref(initial.leftWidth)
  const rightWidth = ref(initial.rightWidth)
  const sync = () => {
    const stored = readGeometry()
    leftWidth.value = stored.leftWidth
    rightWidth.value = stored.rightWidth
  }
  const persist = (patch: Partial<Geometry>) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readGeometry(), ...patch }))
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === null) sync()
  }
  onMounted(() => {
    sync()
    window.addEventListener(CHANGE_EVENT, sync)
    window.addEventListener('storage', onStorage)
  })
  onBeforeUnmount(() => {
    window.removeEventListener(CHANGE_EVENT, sync)
    window.removeEventListener('storage', onStorage)
  })
  return { leftWidth, rightWidth, persist }
}
