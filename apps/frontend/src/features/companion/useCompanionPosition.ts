import { computed, ref, watch, type Ref } from 'vue'
import {
  COMPANION_POSITION_KEY, clampCompanionPosition, clampExpandedPosition,
  companionPositionFromDrag, loadCompanionPosition
} from './position'

interface PositionOptions {
  stage: Ref<HTMLElement | null>
  expanded: Ref<boolean>
  storage: (Pick<Storage, 'getItem' | 'setItem'> & Partial<Pick<Storage, 'removeItem'>>) | null
  onAdjusted?(): void
}

/** Owns placement geometry, persistence and the pointer/resize listener lifetime. */
export function useCompanionPosition(options: PositionOptions) {
  const viewport = () => ({ width: typeof window === 'undefined' ? 1280 : window.innerWidth, height: typeof window === 'undefined' ? 800 : window.innerHeight })
  const saved = loadCompanionPosition(options.storage)
  const position = ref(saved ? clampCompanionPosition(saved, viewport()) : null)
  const dragging = ref(false)
  const rootStyle = computed<Record<string, string>>(() => position.value ? {
    right: `${position.value.right}px`, bottom: `${position.value.bottom}px`, left: 'auto', top: 'auto',
    '--companion-bottom': `${position.value.bottom}px`
  } : {})
  const drag = { active: false, moved: false, startX: 0, startY: 0, offsetX: 0, offsetY: 0, width: 0, height: 0 }
  let suppressClick = false
  let clickTimer: ReturnType<typeof setTimeout> | null = null
  let mounted = false
  let disposed = false
  const persist = () => {
    if (!position.value) return
    try { options.storage?.setItem(COMPANION_POSITION_KEY, JSON.stringify(position.value)) } catch { /* optional */ }
  }
  const ensurePanelVisible = (): boolean => {
    if (!position.value) return false
    const adjusted = clampExpandedPosition(position.value, viewport())
    if (adjusted.right === position.value.right && adjusted.bottom === position.value.bottom) return false
    position.value = adjusted
    persist()
    return true
  }
  const stopWatch = watch(options.expanded, isOpen => { if (isOpen) ensurePanelVisible() })
  const onPointerMove = (event: PointerEvent) => {
    if (!drag.active || disposed) return
    if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5) return
    drag.moved = true
    dragging.value = true
    position.value = companionPositionFromDrag(
      { width: drag.width, height: drag.height }, { x: event.clientX, y: event.clientY },
      { x: drag.offsetX, y: drag.offsetY }, viewport()
    )
  }
  const removeDragListeners = () => {
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
    window.removeEventListener('pointercancel', onPointerUp)
  }
  const onPointerUp = () => {
    removeDragListeners()
    if (!drag.active) return
    drag.active = false
    dragging.value = false
    if (!drag.moved) return
    suppressClick = true
    if (clickTimer !== null) clearTimeout(clickTimer)
    clickTimer = setTimeout(() => { suppressClick = false; clickTimer = null }, 0)
    persist()
    if (options.expanded.value && ensurePanelVisible()) options.onAdjusted?.()
  }
  const onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0 || disposed) return
    const rect = options.stage.value?.getBoundingClientRect()
    if (!rect) return
    Object.assign(drag, { active: true, moved: false, startX: event.clientX, startY: event.clientY,
      offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top, width: rect.width, height: rect.height })
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onPointerUp)
  }
  const onResize = () => {
    if (!position.value) return
    position.value = options.expanded.value
      ? clampExpandedPosition(position.value, viewport()) : clampCompanionPosition(position.value, viewport())
    persist()
  }
  const mount = () => {
    if (mounted || disposed) return
    mounted = true
    window.addEventListener('resize', onResize)
    if (options.expanded.value) ensurePanelVisible()
  }
  const reset = () => {
    position.value = null
    try { options.storage?.removeItem?.(COMPANION_POSITION_KEY) } catch { /* optional */ }
  }
  const dispose = () => {
    disposed = true
    stopWatch()
    removeDragListeners()
    window.removeEventListener('resize', onResize)
    drag.active = false
    dragging.value = false
    if (clickTimer !== null) clearTimeout(clickTimer)
    clickTimer = null
  }
  return { position, dragging, rootStyle, onPointerDown, ensurePanelVisible, reset, mount, dispose, isClickSuppressed: () => suppressClick }
}
