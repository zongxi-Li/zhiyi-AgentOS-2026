import { reactive } from 'vue'

/**
 * VSCode 式全局界面缩放（桌面端）：
 * - Ctrl + 滚轮 / Ctrl+= / Ctrl+- 按档位缩放，Ctrl+0 复位；
 * - 档位 factor = 1.2^level，0 档即 100%，档位写入 localStorage 跨会话恢复；
 * - 本模块只管档位状态与输入接管，真正落地缩放由平台桥注入
 *   （桌面 = webview.setZoom，等效浏览器整页缩放；Web 构建走空占位不初始化）。
 */

export const UI_ZOOM_STORAGE_KEY = 'layout.ui_zoom_level'
export const UI_ZOOM_BASE = 1.2
export const UI_ZOOM_MIN_LEVEL = -4 // 48%
export const UI_ZOOM_MAX_LEVEL = 5 // 249%

// 一格滚轮步进：标准鼠标一格 deltaY≈100，触控板捏合是大量小 delta，留余量累计触发。
const WHEEL_STEP_DELTA = 60
const APPLY_DEBOUNCE_MS = 40
const OSD_HIDE_DELAY_MS = 1400
// 触控板双指捏合在 WebView 上同样以 wheel+ctrlKey 形式上报；deltaMode=line 时按 16px 折算。
const LINE_MODE_PX = 16

export const uiZoomState = reactive({
  level: 0,
  /** 缩放指示条是否可见（交互后短暂显示，空闲后自动隐藏）。 */
  visible: false
})

export const uiZoomFactor = (level: number): number => Math.pow(UI_ZOOM_BASE, level)

export const uiZoomPercentage = (level: number): number => Math.round(uiZoomFactor(level) * 100)

export interface UiZoomOptions {
  /** 把目标档位落到真实缩放（桌面桥 = webview.setZoom）。 */
  apply: (factor: number) => void
  storageKey?: string
  minLevel?: number
  maxLevel?: number
}

type UiZoomRuntime = Required<UiZoomOptions>

let runtime: UiZoomRuntime | null = null
let disposer: (() => void) | null = null
let applyTimer: number | undefined
let hideTimer: number | undefined
let wheelAccumulator = 0

const hideOsd = (): void => {
  uiZoomState.visible = false
  hideTimer = undefined
}

const announceOsd = (): void => {
  uiZoomState.visible = true
  window.clearTimeout(hideTimer)
  hideTimer = window.setTimeout(hideOsd, OSD_HIDE_DELAY_MS)
}

const clampLevel = (level: number): number => {
  if (!runtime) return level
  return Math.min(runtime.maxLevel, Math.max(runtime.minLevel, level))
}

const setLevel = (next: number, options: { persist?: boolean; announce?: boolean } = {}): void => {
  if (!runtime) return
  uiZoomState.level = clampLevel(next)
  if (options.announce) announceOsd()
  if (options.persist !== false) {
    try {
      localStorage.setItem(runtime.storageKey, String(uiZoomState.level))
    } catch {
      // localStorage 不可用（隐私模式等）时只影响跨会话记忆，不影响本次缩放。
    }
  }
  // 滚轮/捏合会高频触发，合并成尾沿一次 IPC 落到 webview。
  window.clearTimeout(applyTimer)
  applyTimer = window.setTimeout(() => {
    applyTimer = undefined
    runtime?.apply(uiZoomFactor(uiZoomState.level))
  }, APPLY_DEBOUNCE_MS)
}

export const zoomIn = (): void => setLevel(uiZoomState.level + 1, { announce: true })

export const zoomOut = (): void => setLevel(uiZoomState.level - 1, { announce: true })

export const resetZoom = (): void => setLevel(0, { announce: true })

const handleWheel = (event: WheelEvent): void => {
  if (!runtime) return
  if (!event.ctrlKey && !event.metaKey) return
  // Ctrl+滚轮收归为窗口级缩放：既阻止 webview 默认行为，也不让画布类组件再消费一次。
  event.preventDefault()
  event.stopPropagation()
  const delta = event.deltaY * (event.deltaMode === 1 ? LINE_MODE_PX : 1)
  wheelAccumulator += delta
  if (wheelAccumulator >= WHEEL_STEP_DELTA) {
    wheelAccumulator -= WHEEL_STEP_DELTA
    zoomIn()
  } else if (wheelAccumulator <= -WHEEL_STEP_DELTA) {
    wheelAccumulator += WHEEL_STEP_DELTA
    zoomOut()
  }
}

const handleKeydown = (event: KeyboardEvent): void => {
  if (!runtime) return
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return
  const isZoomIn = event.key === '=' || event.key === '+' || event.code === 'Equal' || event.code === 'NumpadAdd'
  const isZoomOut = event.key === '-' || event.code === 'Minus' || event.code === 'NumpadSubtract'
  const isReset = event.key === '0' || event.code === 'Digit0' || event.code === 'Numpad0'
  if (isZoomIn) {
    event.preventDefault()
    zoomIn()
  } else if (isZoomOut) {
    event.preventDefault()
    zoomOut()
  } else if (isReset) {
    event.preventDefault()
    resetZoom()
  }
}

const readStoredLevel = (): number => {
  if (!runtime) return 0
  try {
    const stored = Number.parseInt(localStorage.getItem(runtime.storageKey) || '', 10)
    if (Number.isInteger(stored)) return clampLevel(stored)
  } catch {
    // localStorage 不可用时按默认 100% 起步。
  }
  return 0
}

/** 初始化全局缩放接管；幂等，重复调用返回同一个清理函数。 */
export function initUiZoomControl(options: UiZoomOptions): () => void {
  if (disposer) return disposer
  runtime = {
    storageKey: UI_ZOOM_STORAGE_KEY,
    minLevel: UI_ZOOM_MIN_LEVEL,
    maxLevel: UI_ZOOM_MAX_LEVEL,
    ...options
  }

  const restored = readStoredLevel()
  // 无条件按存储值回同步（含 0 档）：dispose 后重新初始化时状态要从存储重算，不能沿用旧值。
  uiZoomState.level = restored
  if (restored !== 0) {
    // 恢复上次档位并短暂展示指示条，让用户知道界面不是 100%。
    setLevel(restored, { persist: false, announce: true })
  }

  window.addEventListener('wheel', handleWheel, { capture: true, passive: false })
  window.addEventListener('keydown', handleKeydown, { capture: true })

  disposer = () => {
    window.removeEventListener('wheel', handleWheel, { capture: true })
    window.removeEventListener('keydown', handleKeydown, { capture: true })
    window.clearTimeout(applyTimer)
    window.clearTimeout(hideTimer)
    applyTimer = undefined
    hideTimer = undefined
    wheelAccumulator = 0
    runtime = null
    disposer = null
    uiZoomState.visible = false
  }
  return disposer
}
