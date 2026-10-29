/**
 * 纯函数 IPC/输入校验：Main Process 所有 handler 的参数先经这里，
 * 不依赖 electron，可被 node --test 直接单测。
 */

/** 只接受 http/https、无内嵌凭据、长度受控的 URL；非法返回 null。 */
export function parseHttpUrl(value: unknown): URL | null {
  if (typeof value !== 'string' || value.length === 0 || value.length > 2048) return null
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return null
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
  if (!parsed.hostname) return null
  // 拒绝 userinfo 形态（http://user:pass@host/），它会被 shell/openExternal 放大。
  if (parsed.username || parsed.password) return null
  if (/[\u0000-\u001f]/.test(value)) return null
  return parsed
}

/**
 * 文件扩展名过滤器：undefined 视为合法（不过滤）；其余必须是
 * ≤16 项、每项 1-12 位字母数字的数组。合法返回去重小写数组，
 * 非法返回 null（调用方必须拒绝）。
 */
export function parseExtensions(value: unknown): string[] | undefined | null {
  if (value === undefined || value === null) return undefined
  if (!Array.isArray(value) || value.length > 16) return null
  const result: string[] = []
  for (const item of value) {
    if (typeof item !== 'string' || !/^[A-Za-z0-9]{1,12}$/.test(item)) return null
    const normalized = item.toLowerCase()
    if (!result.includes(normalized)) result.push(normalized)
  }
  return result
}

/** 有界文本：非字符串、空串或超长返回 null。 */
export function parseBoundedText(value: unknown, maxLength: number): string | null {
  if (typeof value !== 'string' || value.length === 0 || value.length > maxLength) return null
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) return null
  return value
}

/** 严格布尔：非 true/false 返回 null。 */
export function parseBoolean(value: unknown): boolean | null {
  return value === true || value === false ? value : null
}

/** 有界数值：非有限数或越界返回 null。 */
export function clampNumber(value: unknown, min: number, max: number): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.min(max, Math.max(min, value))
}

export interface DisplayArea {
  x: number
  y: number
  height: number
  width: number
}

/** 窗口边界是否还落在任一显示器内（外接屏拔除后丢弃过期坐标）。 */
export function fitsAnyDisplay(bounds: { x: number; y: number; width: number; height: number }, displays: DisplayArea[]): boolean {
  if (!Number.isFinite(bounds.x) || !Number.isFinite(bounds.y)) return false
  return displays.some((display) => bounds.x >= display.x && bounds.y >= display.y
    && bounds.x < display.x + display.width && bounds.y < display.y + display.height)
}
