import { computed, onBeforeUnmount, onMounted, ref, unref, watch, type ComputedRef, type Ref } from 'vue'

export type WorkbenchPaneSide = 'left' | 'right'

export interface WorkbenchPaneConfig {
  minWidth: number
  defaultWidth: number
  maxWidth: number
}

export interface WorkbenchLayoutPersistence {
  leftPaneWidth: number
  rightPaneWidth: number
  bottomPanelHeight?: number
  bottomPanelCollapsedByUser?: boolean
}

export interface UseWorkbenchLayoutOptions {
  storageKey?: string
  left?: Partial<WorkbenchPaneConfig>
  right?: Partial<WorkbenchPaneConfig>
  mainMinWidth?: number
  rightEnabled?: boolean | Ref<boolean> | ComputedRef<boolean>
}

const DEFAULT_STORAGE_KEY = 'zhiyi.acg.workbench.layout.v1'
const DEFAULT_LEFT: WorkbenchPaneConfig = { minWidth: 240, defaultWidth: 320, maxWidth: 520 }
const DEFAULT_RIGHT: WorkbenchPaneConfig = { minWidth: 300, defaultWidth: 400, maxWidth: 640 }
const DEFAULT_MAIN_MIN_WIDTH = 560
const HANDLE_WIDTH = 8

const asFiniteNumber = (value: unknown): number | null => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value
}

const asBoolean = (value: unknown): boolean | null => {
  if (typeof value !== 'boolean') return null
  return value
}

const mergeConfig = (base: WorkbenchPaneConfig, override?: Partial<WorkbenchPaneConfig>): WorkbenchPaneConfig => {
  const minWidth = Math.max(0, Math.round(override?.minWidth ?? base.minWidth))
  const maxWidth = Math.max(minWidth, Math.round(override?.maxWidth ?? base.maxWidth))
  const defaultWidth = Math.min(maxWidth, Math.max(minWidth, Math.round(override?.defaultWidth ?? base.defaultWidth)))
  return { minWidth, defaultWidth, maxWidth }
}

const readPersistence = (storageKey: string): Partial<WorkbenchLayoutPersistence> => {
  if (typeof window === 'undefined') return {}
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(storageKey) || '{}')
    if (!parsed || typeof parsed !== 'object') return {}
    const record = parsed as Record<string, unknown>
    return {
      leftPaneWidth: asFiniteNumber(record.leftPaneWidth) ?? undefined,
      rightPaneWidth: asFiniteNumber(record.rightPaneWidth) ?? undefined,
      bottomPanelHeight: asFiniteNumber(record.bottomPanelHeight) ?? undefined,
      bottomPanelCollapsedByUser: asBoolean(record.bottomPanelCollapsedByUser) ?? undefined
    }
  } catch {
    return {}
  }
}

export const readWorkbenchLayoutPersistence = (storageKey: string): Partial<WorkbenchLayoutPersistence> => (
  readPersistence(storageKey)
)

export const writeWorkbenchLayoutPersistence = (
  storageKey: string,
  patch: Partial<WorkbenchLayoutPersistence>
) => {
  if (typeof window === 'undefined') return
  const current = readPersistence(storageKey)
  window.localStorage.setItem(storageKey, JSON.stringify({ ...current, ...patch }))
}

export const useWorkbenchLayout = (options: UseWorkbenchLayoutOptions = {}) => {
  const storageKey = options.storageKey || DEFAULT_STORAGE_KEY
  const left = mergeConfig(DEFAULT_LEFT, options.left)
  const right = mergeConfig(DEFAULT_RIGHT, options.right)
  const mainMinWidth = Math.max(0, Math.round(options.mainMinWidth ?? DEFAULT_MAIN_MIN_WIDTH))
  const persisted = readPersistence(storageKey)

  const containerRef = ref<HTMLElement | null>(null)
  const containerWidth = ref(0)
  const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
  const leftPaneWidth = ref(Math.min(left.maxWidth, Math.max(left.minWidth, Math.round(persisted.leftPaneWidth ?? left.defaultWidth))))
  const rightPaneWidth = ref(Math.min(right.maxWidth, Math.max(right.minWidth, Math.round(persisted.rightPaneWidth ?? right.defaultWidth))))
  const leftAutoHidden = ref(false)
  const rightAutoHidden = ref(false)
  const resizingSide = ref<WorkbenchPaneSide | null>(null)

  let resizeObserver: ResizeObserver | null = null
  let resizeFrame: number | null = null
  let pendingResizeWidth: number | null = null
  let resizeStartX = 0
  let resizeStartWidth = 0
  let previousBodyCursor = ''
  let previousBodyUserSelect = ''

  const rightEnabled = computed(() => {
    if (typeof options.rightEnabled === 'boolean' || options.rightEnabled === undefined) {
      return options.rightEnabled ?? true
    }
    return Boolean(unref(options.rightEnabled))
  })

  const rightMaxWidth = computed(() => {
    const viewportMax = Math.floor(viewportWidth.value * 0.45)
    return Math.max(right.minWidth, Math.min(right.maxWidth, viewportMax))
  })

  const effectiveRightPaneWidth = computed(() => Math.min(rightPaneWidth.value, rightMaxWidth.value))
  const leftPaneVisible = computed(() => !leftAutoHidden.value)
  const rightPaneVisible = computed(() => rightEnabled.value && !rightAutoHidden.value)

  const persist = () => {
    const value: Partial<WorkbenchLayoutPersistence> = {
      leftPaneWidth: leftPaneWidth.value,
      rightPaneWidth: rightPaneWidth.value
    }
    writeWorkbenchLayoutPersistence(storageKey, value)
  }

  const requiredWidth = (includeLeft: boolean, includeRight: boolean) => (
    mainMinWidth
    + (includeLeft ? leftPaneWidth.value : 0)
    + (includeRight ? effectiveRightPaneWidth.value : 0)
    + (includeLeft ? HANDLE_WIDTH : 0)
    + (includeRight ? HANDLE_WIDTH : 0)
  )

  const syncAutoHidden = () => {
    const width = containerRef.value?.clientWidth || 0
    containerWidth.value = width
    if (!width) {
      // The first observer pass can happen before the workbench has a measurable
      // width. Still honor a pane that was explicitly dragged to its minimum.
      leftAutoHidden.value = leftPaneWidth.value <= left.minWidth
      rightAutoHidden.value = rightEnabled.value && rightPaneWidth.value <= right.minWidth
      return
    }

    const includeLeft = true
    const includeRight = Boolean(rightEnabled.value)
    const shouldAutoHideRight = includeRight && (
      rightPaneWidth.value <= right.minWidth || width < requiredWidth(includeLeft, includeRight)
    )
    const shouldAutoHideLeft = (
      leftPaneWidth.value <= left.minWidth || width < requiredWidth(includeLeft, includeRight && !shouldAutoHideRight)
    )

    rightAutoHidden.value = shouldAutoHideRight
    leftAutoHidden.value = shouldAutoHideLeft
  }

  const maxWidthFor = (side: WorkbenchPaneSide) => {
    const config = side === 'left' ? left : right
    const otherWidth = side === 'left'
      ? (rightPaneVisible.value ? effectiveRightPaneWidth.value + HANDLE_WIDTH : 0)
      : (leftPaneVisible.value ? leftPaneWidth.value + HANDLE_WIDTH : 0)
    const availableMax = containerWidth.value > 0
      ? containerWidth.value - mainMinWidth - otherWidth - HANDLE_WIDTH
      : config.maxWidth
    const configuredMax = side === 'right' ? rightMaxWidth.value : config.maxWidth
    return Math.max(config.minWidth, Math.min(configuredMax, availableMax))
  }

  const cancelResizeFrame = () => {
    if (resizeFrame === null) return
    if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(resizeFrame)
    } else if (typeof window !== 'undefined') {
      window.clearTimeout(resizeFrame)
    }
    resizeFrame = null
  }

  const applyPendingResize = () => {
    resizeFrame = null
    if (pendingResizeWidth === null || !resizingSide.value) return
    if (resizingSide.value === 'left') leftPaneWidth.value = pendingResizeWidth
    else rightPaneWidth.value = pendingResizeWidth
    pendingResizeWidth = null
    syncAutoHidden()
  }

  const scheduleResize = (width: number) => {
    pendingResizeWidth = width
    if (resizeFrame !== null) return
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      resizeFrame = window.requestAnimationFrame(applyPendingResize)
    } else if (typeof window !== 'undefined') {
      resizeFrame = window.setTimeout(applyPendingResize, 16)
    }
  }

  const stopResize = () => {
    if (!resizingSide.value) return
    cancelResizeFrame()
    applyPendingResize()
    resizingSide.value = null
    pendingResizeWidth = null
    if (typeof document !== 'undefined') {
      document.body.style.cursor = previousBodyCursor
      document.body.style.userSelect = previousBodyUserSelect
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResize)
      window.removeEventListener('pointercancel', stopResize)
    }
    persist()
    syncAutoHidden()
  }

  const handlePointerMove = (event: PointerEvent) => {
    if (!resizingSide.value) return
    const delta = event.clientX - resizeStartX
    const nextWidth = resizingSide.value === 'left'
      ? resizeStartWidth + delta
      : resizeStartWidth - delta
    const config = resizingSide.value === 'left' ? left : right
    scheduleResize(Math.min(maxWidthFor(resizingSide.value), Math.max(config.minWidth, Math.round(nextWidth))))
  }

  const startResize = (side: WorkbenchPaneSide, event: PointerEvent) => {
    if (event.button !== 0 || resizingSide.value) return
    event.preventDefault()
    resizeStartX = event.clientX
    resizeStartWidth = side === 'left' ? leftPaneWidth.value : rightPaneWidth.value
    resizingSide.value = side
    if (typeof document !== 'undefined') {
      previousBodyCursor = document.body.style.cursor
      previousBodyUserSelect = document.body.style.userSelect
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('pointermove', handlePointerMove)
      window.addEventListener('pointerup', stopResize)
      window.addEventListener('pointercancel', stopResize)
    }
  }

  const adjustWidth = (side: WorkbenchPaneSide, delta: number) => {
    const config = side === 'left' ? left : right
    const current = side === 'left' ? leftPaneWidth.value : rightPaneWidth.value
    const next = Math.min(maxWidthFor(side), Math.max(config.minWidth, current + delta))
    if (side === 'left') leftPaneWidth.value = next
    else rightPaneWidth.value = next
    persist()
    syncAutoHidden()
  }

  const handleResizeKeydown = (side: WorkbenchPaneSide, event: KeyboardEvent) => {
    const step = event.shiftKey ? 24 : 8
    if (event.key === 'Home') adjustWidth(side, side === 'left' ? -leftPaneWidth.value : -rightPaneWidth.value)
    else if (event.key === 'End') {
      const config = side === 'left' ? left : right
      const current = side === 'left' ? leftPaneWidth.value : rightPaneWidth.value
      adjustWidth(side, maxWidthFor(side) - Math.max(config.minWidth, current))
    } else if (event.key === 'ArrowLeft') adjustWidth(side, side === 'left' ? -step : step)
    else if (event.key === 'ArrowRight') adjustWidth(side, side === 'left' ? step : -step)
    else return
    event.preventDefault()
  }

  const resetWidth = (side: WorkbenchPaneSide) => {
    if (side === 'left') leftPaneWidth.value = left.defaultWidth
    else rightPaneWidth.value = right.defaultWidth
    persist()
    syncAutoHidden()
  }

  const handleViewportResize = () => {
    viewportWidth.value = typeof window === 'undefined' ? viewportWidth.value : window.innerWidth
    syncAutoHidden()
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      window.addEventListener('resize', handleViewportResize)
    }
    if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
      resizeObserver = new ResizeObserver(() => syncAutoHidden())
      resizeObserver.observe(containerRef.value)
    }
    syncAutoHidden()
  })

  watch(rightEnabled, syncAutoHidden)

  onBeforeUnmount(() => {
    stopResize()
    resizeObserver?.disconnect()
    resizeObserver = null
    if (typeof window !== 'undefined') window.removeEventListener('resize', handleViewportResize)
  })

  return {
    containerRef,
    containerWidth,
    leftPaneWidth,
    rightPaneWidth,
    effectiveRightPaneWidth,
    rightMaxWidth,
    rightEnabled,
    leftAutoHidden,
    rightAutoHidden,
    resizingSide,
    leftPaneVisible,
    rightPaneVisible,
    startResize,
    stopResize,
    handleResizeKeydown,
    resetWidth,
    syncAutoHidden
  }
}
