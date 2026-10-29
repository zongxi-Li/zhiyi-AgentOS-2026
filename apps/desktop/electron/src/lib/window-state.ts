/**
 * 窗口状态持久化的纯逻辑：读写文件留在 Main Process，这里只做
 * 解析、校验与序列化，可被 node --test 直接单测。
 */

export interface WindowState {
  width: number
  height: number
  x?: number
  y?: number
  isMaximized: boolean
}

export const DEFAULT_WINDOW_STATE: WindowState = { width: 1440, height: 900, isMaximized: false }

const MIN_EDGE = 200
const MAX_EDGE = 20000

function parseEdge(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  if (value < MIN_EDGE || value > MAX_EDGE) return fallback
  return Math.round(value)
}

/** 容错解析状态文件：任何字段异常都退回默认或丢弃该字段，永不抛错。 */
export function parseWindowState(raw: string | null | undefined, fallback: WindowState = DEFAULT_WINDOW_STATE): WindowState {
  let data: unknown
  try {
    data = JSON.parse(raw ?? '')
  } catch {
    return { ...fallback }
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return { ...fallback }
  const record = data as Record<string, unknown>
  const state: WindowState = {
    width: parseEdge(record.width, fallback.width),
    height: parseEdge(record.height, fallback.height),
    isMaximized: record.isMaximized === true
  }
  if (typeof record.x === 'number' && Number.isFinite(record.x) && Math.abs(record.x) <= MAX_EDGE) {
    state.x = Math.round(record.x)
  }
  if (typeof record.y === 'number' && Number.isFinite(record.y) && Math.abs(record.y) <= MAX_EDGE) {
    state.y = Math.round(record.y)
  }
  return state
}

export interface WindowBounds {
  x: number
  y: number
  width: number
  height: number
}

/** 关闭时序列化：用 normalBounds（最大化时还原尺寸），叠加最大化和全屏标志。 */
export function serializeWindowState(bounds: WindowBounds, isMaximized: boolean, isFullscreen: boolean): string {
  return JSON.stringify({
    x: Math.round(bounds.x),
    y: Math.round(bounds.y),
    width: Math.round(bounds.width),
    height: Math.round(bounds.height),
    isMaximized,
    isFullscreen
  })
}

/**
 * 坐标不再落在任何显示器（外接屏拔除）时丢弃 x/y 回到居中，
 * 尺寸保留。显示器为空列表同样只丢坐标。
 */
export function dropStalePosition(state: WindowState, fitsDisplay: (bounds: WindowBounds) => boolean): WindowState {
  if (state.x === undefined || state.y === undefined) return state
  const onScreen = fitsDisplay({ x: state.x, y: state.y, width: state.width, height: state.height })
  if (onScreen) return state
  const next: WindowState = { width: state.width, height: state.height, isMaximized: state.isMaximized }
  return next
}
